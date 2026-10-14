"""
Content repository - database access for Content model.

Supports multi-provider upsert with deduplication via external IDs and
title+year matching.
"""

import json
import logging
import re
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, defer

from app.models.content import Content
from app.models.external_id import ContentExternalId
from app.services.identity import ID_KINDS, ids_disagree
from app.services.providers.base import NormalizedContent, _year_from_date

logger = logging.getLogger(__name__)


def _parse_datetime(date_str: str | None) -> datetime | None:
    """Best-effort parse of YYYY-MM-DD (or YYYY) into a tz-aware datetime."""
    if not date_str:
        return None
    s = str(date_str).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y"):
        try:
            dt = datetime.strptime(s, fmt)
            return dt.replace(tzinfo=UTC)
        except ValueError:
            continue
    m = re.match(r"(\d{4})", s)
    if m:
        return datetime(int(m.group(1)), 1, 1, tzinfo=UTC)
    return None


_BULK_CHUNK = 500  # titles per lookup query / multi-row insert


def _nc_ids(nc: NormalizedContent) -> dict[str, str]:
    """The provider ids an incoming item carries, as text (the external-id table keeps text)."""
    return {kind: str(getattr(nc, f"{kind}_id")) for kind in ID_KINDS if getattr(nc, f"{kind}_id")}


def _ids_conflict(known: Mapping[str, Any], nc: NormalizedContent) -> bool:
    """True if a stored title's ids (``known``, from the external-id table) and the incoming item
    carry the same kind of external id with different values: they are then different titles even
    if name and year match."""
    return ids_disagree({k: str(v) for k, v in known.items()}, _nc_ids(nc))


def _external_ids_for(db: Session, content_ids: Iterable[int]) -> dict[int, dict[str, str]]:
    """{content id: {provider: external id}} read from the external-id table, in batches.

    A title with several ids of one provider (kept apart by kind) gets the first one found.
    """
    wanted = sorted(set(content_ids))
    found: dict[int, dict[str, str]] = {cid: {} for cid in wanted}
    for start in range(0, len(wanted), _BULK_CHUNK):
        rows = db.execute(
            select(ContentExternalId.content_id, ContentExternalId.provider, ContentExternalId.external_id)
            .where(ContentExternalId.content_id.in_(wanted[start : start + _BULK_CHUNK]))
            .order_by(ContentExternalId.provider, ContentExternalId.kind, ContentExternalId.external_id)
        )
        for cid, provider, value in rows:
            found[cid].setdefault(provider, value)
    return found


def _rows_by_external_id(
    db: Session, provider: str, content_type: str | None, values: list[str]
) -> list[tuple[str, Content]]:
    """(external id, title) pairs for the given ids, read from the external-id table, lowest title id first.

    ``content_type`` None means the id is global (IMDb ids number titles of every type).
    """
    pairs: list[tuple[str, Content]] = []
    for start in range(0, len(values), _BULK_CHUNK):
        chunk = values[start : start + _BULK_CHUNK]
        conditions = [ContentExternalId.provider == provider, ContentExternalId.external_id.in_(chunk)]
        if content_type:
            conditions.append(ContentExternalId.kind == content_type)
        query = (
            db.query(ContentExternalId.external_id, Content)
            .join(Content, Content.id == ContentExternalId.content_id)
            # the embedding vectors are large and never needed for matching
            .options(defer(Content.embedding))
            .filter(*conditions)
            .order_by(Content.id)
        )
        pairs.extend((str(ext), row) for ext, row in query.all())
    return pairs


def _id_triples(content_type: str, ids: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(provider, kind, external id) for every id present; kind is the content type the id numbers."""
    return [(kind, content_type, str(ids[kind])) for kind in ID_KINDS if ids.get(kind)]


class _ExistingIndex:
    """Looks up the stored rows that incoming titles match, in a few batched queries."""

    def __init__(self, db: Session, items: list[NormalizedContent]):
        self.imdb: dict[str, Content] = {}
        self.numeric: dict[tuple[str, str, int], Content] = {}
        self.by_title: dict[tuple[str, str], list[Content]] = {}
        self._load_ids(db, items)
        self._load_titles(db, items)
        self.ids: dict[int, dict[str, str]] = _external_ids_for(db, (row.id for row in self._all_rows()))

    def _all_rows(self) -> list[Content]:
        rows = list(self.imdb.values()) + list(self.numeric.values())
        for group in self.by_title.values():
            rows.extend(group)
        return rows

    def _rows(self, db: Session, *conditions: Any) -> list[Content]:
        # the embedding vectors are large and never needed for matching
        query = db.query(Content).options(defer(Content.embedding)).filter(*conditions)  # type: ignore[arg-type]
        rows: list[Content] = query.order_by(Content.id).all()
        return rows

    def _load_ids(self, db: Session, items: list[NormalizedContent]) -> None:
        imdb_ids = sorted({nc.imdb_id for nc in items if nc.imdb_id})
        for value, row in _rows_by_external_id(db, "imdb", None, imdb_ids):
            self.imdb.setdefault(value, row)
        for content_type in {nc.content_type for nc in items}:
            for kind in ("tmdb", "tvdb", "tvmaze"):
                ids = sorted(
                    {
                        str(getattr(nc, f"{kind}_id"))
                        for nc in items
                        if nc.content_type == content_type and getattr(nc, f"{kind}_id")
                    }
                )
                for value, row in _rows_by_external_id(db, kind, content_type, ids):
                    self.numeric.setdefault((content_type, kind, int(value)), row)

    def _load_titles(self, db: Session, items: list[NormalizedContent]) -> None:
        for content_type in {nc.content_type for nc in items}:
            titles = sorted({nc.title for nc in items if nc.content_type == content_type and self._by_id(nc) is None})
            for start in range(0, len(titles), _BULK_CHUNK):
                for row in self._rows(
                    db, Content.content_type == content_type, Content.title.in_(titles[start : start + _BULK_CHUNK])
                ):
                    self.by_title.setdefault((content_type, str(row.title)), []).append(row)

    def _by_id(self, nc: NormalizedContent) -> Content | None:
        if nc.imdb_id and nc.imdb_id in self.imdb:
            return self.imdb[nc.imdb_id]
        for kind in ("tmdb", "tvdb", "tvmaze"):
            value = getattr(nc, f"{kind}_id")
            if value and (nc.content_type, kind, value) in self.numeric:
                return self.numeric[(nc.content_type, kind, value)]
        return None

    def match(self, nc: NormalizedContent) -> Content | None:
        hit = self._by_id(nc)
        if hit is not None:
            return hit
        for row in self.by_title.get((nc.content_type, nc.title), []):
            if nc.year and not (row.release_date or "").startswith(str(nc.year)):
                continue
            if not _ids_conflict(self.ids[row.id], nc):
                return row
        return None


class _PendingIndex:
    """Titles in the current batch that are about to be inserted, so later items can merge into them."""

    def __init__(self) -> None:
        self.items: list[NormalizedContent] = []
        self._ids: dict[tuple[Any, ...], NormalizedContent] = {}
        self._titles: dict[tuple[str, str], list[NormalizedContent]] = {}

    @staticmethod
    def _id_keys(nc: NormalizedContent) -> list[tuple[Any, ...]]:
        keys: list[tuple[Any, ...]] = [("imdb", nc.imdb_id)] if nc.imdb_id else []
        for kind in ("tmdb", "tvdb", "tvmaze"):
            value = getattr(nc, f"{kind}_id")
            if value:
                keys.append((nc.content_type, kind, value))
        return keys

    def add(self, nc: NormalizedContent) -> None:
        self.items.append(nc)
        for key in self._id_keys(nc):
            self._ids.setdefault(key, nc)
        self._titles.setdefault((nc.content_type, nc.title), []).append(nc)

    def match(self, nc: NormalizedContent) -> NormalizedContent | None:
        for key in self._id_keys(nc):
            if key in self._ids:
                return self._ids[key]
        for other in self._titles.get((nc.content_type, nc.title), []):
            other_year = other.year or _year_from_date(other.release_date)
            if nc.year and other_year != nc.year:
                continue
            if not _ids_conflict(_nc_ids(other), nc):
                return other
        return None


class ContentRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- single-row lookups ---- #

    def get_by_id(self, content_id: int) -> Content | None:
        return self.db.query(Content).filter(Content.id == content_id).first()

    def get_by_imdb_id(self, imdb_id: str) -> Content | None:
        return self._first_by_external_id("imdb", imdb_id, None)

    def get_by_tmdb_id(self, tmdb_id: int, content_type: str | None = None) -> Content | None:
        return self._first_by_external_id("tmdb", tmdb_id, content_type)

    def get_by_tvdb_id(self, tvdb_id: int, content_type: str | None = None) -> Content | None:
        return self._first_by_external_id("tvdb", tvdb_id, content_type)

    def get_by_tvmaze_id(self, tvmaze_id: int, content_type: str | None = None) -> Content | None:
        return self._first_by_external_id("tvmaze", tvmaze_id, content_type)

    def _first_by_external_id(self, provider: str, value: Any, content_type: str | None) -> Content | None:
        """Read the external-id table. Movies and series are numbered separately by TVDB and
        TMDb, so a numeric id only identifies a title within its own type; pass ``content_type``
        to say which."""
        query = (
            self.db.query(Content)
            .join(ContentExternalId, ContentExternalId.content_id == Content.id)
            .filter(ContentExternalId.provider == provider, ContentExternalId.external_id == str(value))
        )
        if content_type:
            query = query.filter(ContentExternalId.kind == content_type)
        return query.order_by(Content.id).first()

    def external_ids_for(self, content_ids: list[int]) -> dict[int, dict[str, str]]:
        """{content id: {provider: external id}} for the given titles, from the external-id table."""
        return _external_ids_for(self.db, content_ids)

    def record_external_ids(self, titles: list[tuple[int, str, dict[str, Any]]], known_new: bool = False) -> None:
        """Make sure the external-id table has a row for every id of the given titles.

        ``titles`` is (content id, content type, {kind: id value}). Rows already there are left
        alone, so this is safe to repeat. ``known_new`` says the titles were just created, so there is
        nothing to look up first.
        """
        wanted: dict[tuple[str, str, str], int] = {}
        for content_id, content_type, ids in titles:
            for triple in _id_triples(content_type, ids):
                wanted.setdefault(triple, content_id)
        if not wanted:
            return
        by_group: dict[tuple[str, str], list[str]] = {}
        for provider, kind, value in wanted:
            by_group.setdefault((provider, kind), []).append(value)
        present: set[tuple[str, str, str]] = set()
        for (provider, kind), values in {} if known_new else by_group.items():
            for start in range(0, len(values), _BULK_CHUNK):
                found = self.db.execute(
                    select(ContentExternalId.external_id).where(
                        ContentExternalId.provider == provider,
                        ContentExternalId.kind == kind,
                        ContentExternalId.external_id.in_(values[start : start + _BULK_CHUNK]),
                    )
                )
                present.update((provider, kind, v) for v in found.scalars())
        rows = [
            {"provider": p, "kind": k, "external_id": v, "content_id": cid}
            for (p, k, v), cid in wanted.items()
            if (p, k, v) not in present
        ]
        for start in range(0, len(rows), _BULK_CHUNK):
            chunk = rows[start : start + _BULK_CHUNK]
            try:
                with self.db.begin_nested():
                    self.db.execute(ContentExternalId.__table__.insert().values(chunk))
            except Exception as e:
                logger.warning("Bulk insert of %d external ids failed (%s); saving them one by one", len(chunk), e)
                for row in chunk:
                    try:
                        with self.db.begin_nested():
                            self.db.execute(ContentExternalId.__table__.insert().values([row]))
                    except Exception as e2:
                        logger.warning("Could not record %s id %s: %s", row["provider"], row["external_id"], e2)

    def get_by_title_year_type(self, title: str, year: int | None, content_type: str) -> Content | None:
        return next(iter(self._all_by_title_year_type(title, year, content_type)), None)

    def _all_by_title_year_type(self, title: str, year: int | None, content_type: str) -> list[Content]:
        q = self.db.query(Content).filter(
            Content.title == title,
            Content.content_type == content_type,
        )
        if year:
            q = q.filter(Content.release_date.like(f"{year}%"))
        matches: list[Content] = q.all()
        return matches

    # ---- list queries ---- #

    def get_movies(
        self,
        filter_by: str = "all",
        search: str | None = None,
        limit: int = 40,
        offset: int = 0,
    ) -> list[Content]:
        query = self.db.query(Content).filter(Content.content_type == "movie")
        query = self._apply_filters(query, filter_by, search)
        return query.offset(offset).limit(limit).all()

    def get_tv_shows(
        self,
        filter_by: str = "all",
        search: str | None = None,
        limit: int = 40,
        offset: int = 0,
    ) -> list[Content]:
        query = self.db.query(Content).filter(Content.content_type == "tv_show")
        query = self._apply_filters(query, filter_by, search)
        return query.offset(offset).limit(limit).all()

    # ---- Home page sections ---- #

    def get_recent(self, content_type: str | None = None, limit: int = 12) -> list[Content]:
        """Already-released titles, newest first. Used for "New This Week".

        release_date is a free-text column and a handful of rows carry an
        implausible value straight from the source (TVDB has at least one
        title dated "9696-01-01" — a typo on their end). That sorts to the
        very top of a plain string ORDER BY, so both bounds are checked
        against today, not just "has a date".
        """
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        query = self.db.query(Content).filter(Content.release_date.isnot(None), Content.release_date <= today)
        if content_type:
            query = query.filter(Content.content_type == content_type)
        return query.order_by(Content.release_date.desc()).limit(limit).all()

    def get_top_rated(self, content_type: str | None = None, limit: int = 12) -> list[Content]:
        """Highest-rated titles in the catalog, on the usual 0-10 scale."""
        query = self.db.query(Content).filter(Content.rating.isnot(None), Content.rating <= 10)
        if content_type:
            query = query.filter(Content.content_type == content_type)
        return query.order_by(Content.rating.desc()).limit(limit).all()

    def get_coming_soon(self, content_type: str | None = None, limit: int = 12) -> list[Content]:
        """Titles releasing after today and within a few years, soonest first.

        The upper bound excludes the same class of bad source data as
        get_recent (a bare typo'd year would otherwise look like the
        furthest-out "coming soon" title there is).
        """
        today = datetime.now(UTC)
        today_str = today.strftime("%Y-%m-%d")
        cutoff_str = (today + timedelta(days=3 * 365)).strftime("%Y-%m-%d")
        query = self.db.query(Content).filter(Content.release_date > today_str, Content.release_date <= cutoff_str)
        if content_type:
            query = query.filter(Content.content_type == content_type)
        return query.order_by(Content.release_date.asc()).limit(limit).all()

    def get_trending_by_library_adds(
        self, content_type: str | None = None, days: int = 7, limit: int = 12
    ) -> list[Content]:
        """Titles most added to any user's library in the last `days` days."""
        from sqlalchemy import func

        from app.models import LibraryItem

        query = (
            self.db.query(Content)
            .join(LibraryItem)
            .filter(LibraryItem.added_at >= datetime.now(UTC) - timedelta(days=days))
        )
        if content_type:
            query = query.filter(Content.content_type == content_type)
        return query.group_by(Content.id).order_by(func.count(LibraryItem.id).desc()).limit(limit).all()

    def browse(
        self,
        query_str: str | None = None,
        content_type: str | None = None,
        genre: str | None = None,
        sort: str = "relevance",
        limit: int = 40,
        offset: int = 0,
    ) -> tuple[list[Content], int]:
        """Unified search/browse for the Search Results page. Returns (results, total_count)."""
        q = self.db.query(Content)
        if query_str:
            q = q.filter(
                or_(
                    Content.title.ilike(f"%{query_str}%"),
                    Content.description.ilike(f"%{query_str}%"),
                )
            )
        if content_type and content_type != "all":
            q = q.filter(Content.content_type == content_type)
        if genre:
            q = q.filter(Content.genres.ilike(f'%"{genre}"%'))

        total = q.count()

        if sort == "top_rated":
            q = q.order_by(Content.rating.desc().nullslast())
        elif sort == "recent":
            q = q.order_by(Content.release_date.desc().nullslast())
        elif query_str:
            q = q.order_by(Content.title)
        else:
            q = q.order_by(Content.release_date.desc().nullslast())

        return q.offset(offset).limit(limit).all(), total

    def count(self, content_type: str | None = None) -> int:
        query = self.db.query(Content)
        if content_type:
            query = query.filter(Content.content_type == content_type)
        return query.count()

    def search(self, query_str: str, content_type: str | None = None, limit: int = 20) -> list[Content]:
        query = self.db.query(Content).filter(Content.title.ilike(f"%{query_str}%"))
        if content_type:
            query = query.filter(Content.content_type == content_type)
        return query.limit(limit).all()

    def get_all_ids(self, content_type: str | None = None) -> list[int]:
        query = self.db.query(Content.id)
        if content_type:
            query = query.filter(Content.content_type == content_type)
        return [row[0] for row in query.all()]

    # ---- dedup-aware upsert from NormalizedContent ---- #

    def find_existing(self, nc: NormalizedContent) -> Content | None:
        """Find an existing Content row matching by external IDs or title+year."""
        if nc.imdb_id:
            hit = self.get_by_imdb_id(nc.imdb_id)
            if hit:
                return hit
        if nc.tmdb_id:
            hit = self.get_by_tmdb_id(nc.tmdb_id, nc.content_type)
            if hit:
                return hit
        if nc.tvdb_id:
            hit = self.get_by_tvdb_id(nc.tvdb_id, nc.content_type)
            if hit:
                return hit
        if nc.tvmaze_id:
            hit = self.get_by_tvmaze_id(nc.tvmaze_id, nc.content_type)
            if hit:
                return hit
        candidates = self._all_by_title_year_type(nc.title, nc.year, nc.content_type)
        known = self.external_ids_for([c.id for c in candidates])
        for candidate in candidates:
            if not _ids_conflict(known[candidate.id], nc):
                return candidate
        return None

    def stored_sharing_ids(self, items: list[NormalizedContent]) -> list[list[Content]]:
        """For each item, the distinct stored titles that share any of its provider ids (lowest id first).

        Same scoping as matching: IMDb ids are global, the others only count within the item's type.
        """
        found: dict[tuple[str, str | None, str], list[Content]] = {}
        wanted: dict[tuple[str, str | None], set[str]] = {}
        for nc in items:
            for kind in ID_KINDS:
                value = getattr(nc, f"{kind}_id")
                if value:
                    wanted.setdefault((kind, None if kind == "imdb" else nc.content_type), set()).add(str(value))
        for (kind, content_type), values in wanted.items():
            for value, row in _rows_by_external_id(self.db, kind, content_type, sorted(values)):
                found.setdefault((kind, content_type, value), []).append(row)
        result: list[list[Content]] = []
        for nc in items:
            rows: dict[int, Content] = {}
            for kind in ID_KINDS:
                value = getattr(nc, f"{kind}_id")
                if value:
                    key = (kind, None if kind == "imdb" else nc.content_type, str(value))
                    for row in found.get(key, []):
                        rows.setdefault(row.id, row)
            result.append(sorted(rows.values(), key=lambda r: r.id))
        return result

    def upsert_normalized(self, nc: NormalizedContent) -> Content:
        """Insert or merge a NormalizedContent into the DB, deduplicating."""
        existing = self.find_existing(nc)
        if existing:
            ids = self._merge_into(existing, nc)
            self.record_external_ids([(int(existing.id), str(existing.content_type), ids)])
            return existing

        content = Content(**self._new_row(nc))
        self.db.add(content)
        self.db.flush()
        self.record_external_ids([(int(content.id), str(content.content_type), dict(_nc_ids(nc)))], known_new=True)
        return content

    @staticmethod
    def _new_row(nc: NormalizedContent) -> dict[str, Any]:
        """Column values for a new Content row (without timestamps)."""
        return {
            "title": nc.title[:200],
            "content_type": nc.content_type,
            "description": (nc.description or "")[:500] or None,
            "genres": json.dumps(nc.genres) if nc.genres else None,
            "poster_url": nc.poster_url,
            "backdrop_url": nc.backdrop_url,
            "release_date": nc.release_date,
            "runtime": nc.runtime,
            "rating": nc.rating,
            "director": nc.director,
            "seasons": nc.seasons,
            "episodes": nc.episodes,
            "status": nc.status,
            "network": nc.network,
            "provider": nc.provider,
            "language": nc.language,
            "country": nc.country,
            "premiere_date": _parse_datetime(nc.premiered),
            "next_episode_date": _parse_datetime(nc.next_episode_date),
        }

    def bulk_upsert_normalized(self, items: list[NormalizedContent]) -> int:
        """Upsert many NormalizedContent items; returns the count saved.

        Matching and inserting are done in batches (a few statements per ``_BULK_CHUNK``
        titles, not several per title): a database round trip can cost hundreds of
        milliseconds from a remote worker. Matching follows ``find_existing``: imdb id,
        then tmdb / tvdb / tvmaze id within the same type, then name and year.
        """
        saved = 0
        for start in range(0, len(items), _BULK_CHUNK):
            saved += self._bulk_upsert_chunk(items[start : start + _BULK_CHUNK])
        return saved

    def _bulk_upsert_chunk(self, items: list[NormalizedContent]) -> int:
        valid: list[NormalizedContent] = []
        for nc in items:
            try:
                self._new_row(nc)  # fails early for an item that could never be saved
                valid.append(nc)
            except Exception as e:
                logger.warning("Failed to upsert %r: %s", getattr(nc, "title", None), e)

        existing = _ExistingIndex(self.db, valid)
        pending = _PendingIndex()
        merged: dict[int, Content] = {}
        for nc in valid:
            row = existing.match(nc)
            if row is not None:
                existing.ids[row.id] = self._merge_into(row, nc, known_ids=existing.ids[row.id])
                merged[row.id] = row
                continue
            twin = pending.match(nc)
            if twin is not None:
                twin.merge(nc)
            else:
                pending.add(nc)

        now = datetime.now(UTC)
        rows = []
        for nc in pending.items:
            values = self._new_row(nc)
            values.update(is_adaptation=False, created_at=now, updated_at=now)
            rows.append((values, _nc_ids(nc)))
        failed, inserted = self._insert_rows(rows)
        self.record_external_ids(
            [(int(row.id), str(row.content_type), existing.ids[row.id]) for row in merged.values()]
        )
        self.record_external_ids(inserted, known_new=True)
        return len(valid) - failed

    def _insert_rows(
        self, rows: list[tuple[dict[str, Any], dict[str, str]]]
    ) -> tuple[int, list[tuple[int, str, dict[str, Any]]]]:
        """Insert rows (column values, provider ids) with one multi-row INSERT per chunk.

        Returns how many could not be saved, and (id, type, provider ids) of each saved row so
        the caller can record its external ids.
        """
        table = Content.__table__
        returned = [table.c.id, table.c.content_type, table.c.title]
        failed = 0
        inserted: list[tuple[int, str, dict[str, Any]]] = []

        def keep(chunk: list[tuple[dict[str, Any], dict[str, str]]], result: Any) -> None:
            # The ids recorded are the ones we just sent, matched to the new rows by type and title
            # (ids from a sequence rise in the order of the rows).
            waiting: dict[tuple[str, str], list[dict[str, str]]] = {}
            for values, ids in chunk:
                waiting.setdefault((values["content_type"], values["title"]), []).append(ids)
            for r in sorted(result, key=lambda r: r.id):
                inserted.append((r.id, r.content_type, waiting[(r.content_type, r.title)].pop(0)))

        for start in range(0, len(rows), _BULK_CHUNK):
            chunk = rows[start : start + _BULK_CHUNK]
            try:
                with self.db.begin_nested():
                    keep(chunk, self.db.execute(table.insert().values([v for v, _ in chunk]).returning(*returned)))
            except Exception as e:
                logger.warning("Bulk insert of %d titles failed (%s); saving them one by one", len(chunk), e)
                for row in chunk:
                    try:
                        with self.db.begin_nested():
                            keep([row], self.db.execute(table.insert().values([row[0]]).returning(*returned)))
                    except Exception as e2:
                        failed += 1
                        logger.warning("Failed to save %r: %s", row[0].get("title"), e2)
        return failed, inserted

    # Legacy method kept for backward compat with old TMDB-dict ingestion
    def upsert_from_api(self, data: dict[str, Any], content_type: str) -> Content:
        tmdb_id = data.get("id")
        existing = self.get_by_tmdb_id(tmdb_id, content_type) if tmdb_id else None
        title = data.get("title") or data.get("name", "")
        if not existing:
            existing = self.get_by_title_year_type(title, None, content_type)
        if existing:
            ids = self._update_from_api(existing, data, content_type)
            self.record_external_ids([(int(existing.id), str(existing.content_type), ids)])
            return existing
        content = self._create_from_api(data, content_type)
        self.db.add(content)
        self.db.flush()
        new_ids = {"tmdb": str(data["id"])} if data.get("id") else {}
        self.record_external_ids([(int(content.id), str(content.content_type), new_ids)])
        return content

    def bulk_upsert(self, items: list[dict[str, Any]], content_type: str) -> int:
        count = 0
        for item in items:
            try:
                self.upsert_from_api(item, content_type)
                count += 1
            except Exception as e:
                logger.warning("Failed to upsert content: %s", e)
        self.db.commit()
        return count

    # ---- internal helpers ---- #

    def _merge_into(
        self,
        content: Content,
        nc: NormalizedContent,
        overwrite: bool = False,
        known_ids: Mapping[str, str] | None = None,
    ) -> dict[str, str]:
        """Fill blanks on an existing row from a NormalizedContent.

        With ``overwrite`` the provider-owned fields (status, rating, season and episode
        counts) also take the provider's newer value; a title with ``refresh_locked`` set
        is never overwritten.

        ``known_ids`` are the title's ids in the external-id table (looked up when not given).
        An id the title has none of yet is taken from ``nc``. Returns the title's ids after the merge.
        """
        known = dict(known_ids if known_ids is not None else self.external_ids_for([content.id])[content.id])
        embedding_input_changed = False
        if overwrite and not content.refresh_locked:
            for field in ("status", "rating", "seasons", "episodes"):
                value = getattr(nc, field)
                if value is not None:
                    setattr(content, field, value)
        if nc.description and not content.description:
            content.description = nc.description[:500]
            embedding_input_changed = True
        if nc.poster_url and not content.poster_url:
            content.poster_url = nc.poster_url
        if nc.backdrop_url and not content.backdrop_url:
            content.backdrop_url = nc.backdrop_url
        if nc.rating and not content.rating:
            content.rating = nc.rating
        if nc.runtime and not content.runtime:
            content.runtime = nc.runtime
        if nc.director and not content.director:
            content.director = nc.director
        if nc.genres and not content.genres:
            content.genres = json.dumps(nc.genres)
            embedding_input_changed = True
        if nc.status and not content.status:
            content.status = nc.status
        if nc.network and not content.network:
            content.network = nc.network
        if nc.seasons and not content.seasons:
            content.seasons = nc.seasons
        if nc.episodes and not content.episodes:
            content.episodes = nc.episodes
        if nc.release_date and not content.release_date:
            content.release_date = nc.release_date
        incoming = _nc_ids(nc)
        for kind in ID_KINDS:
            if kind in incoming and kind not in known:
                known[kind] = incoming[kind]
        if nc.language and not content.language:
            content.language = nc.language
        if nc.country and not content.country:
            content.country = nc.country
        if nc.premiered and not content.premiere_date:
            content.premiere_date = _parse_datetime(nc.premiered)
        if nc.next_episode_date:
            content.next_episode_date = _parse_datetime(nc.next_episode_date)
        content.updated_at = datetime.now(UTC)
        if embedding_input_changed:
            content.embedding_hash = None  # mark for re-embedding (SCE-33)
        return known

    def _apply_filters(self, query, filter_by: str, search: str | None):
        if search:
            query = query.filter(
                or_(
                    Content.title.ilike(f"%{search}%"),
                    Content.description.ilike(f"%{search}%"),
                )
            )
        if filter_by == "trending":
            query = query.order_by(Content.rating.desc().nullslast())
        elif filter_by == "recent":
            query = query.order_by(Content.created_at.desc())
        else:
            # Newest release first; titles without a release date go last.
            query = query.order_by(Content.release_date.desc().nullslast(), Content.id.desc())
        return query

    def _create_from_api(self, data: dict[str, Any], content_type: str) -> Content:
        title = data.get("title") or data.get("name", "")
        poster_path = data.get("poster_path", "")
        backdrop_path = data.get("backdrop_path", "")
        img_base = "https://image.tmdb.org/t/p/w500"
        backdrop_base = "https://image.tmdb.org/t/p/original"
        return Content(
            title=title[:200],
            content_type=content_type,
            description=(data.get("overview") or "")[:500],
            poster_url=f"{img_base}{poster_path}"
            if poster_path and not poster_path.startswith("http")
            else poster_path,
            backdrop_url=f"{backdrop_base}{backdrop_path}"
            if backdrop_path and not backdrop_path.startswith("http")
            else backdrop_path,
            rating=data.get("vote_average"),
            release_date=data.get("release_date") or data.get("first_air_date"),
            genres=str(data.get("genre_ids", [])),
            provider="tmdb",
        )

    def _update_from_api(self, content: Content, data: dict[str, Any], content_type: str) -> dict[str, str]:
        known = self.external_ids_for([content.id])[content.id]
        img_base = "https://image.tmdb.org/t/p/w500"
        backdrop_base = "https://image.tmdb.org/t/p/original"
        if data.get("overview") and not content.description:
            content.description = data["overview"][:500]
        if data.get("poster_path") and not content.poster_url:
            pp = data["poster_path"]
            content.poster_url = f"{img_base}{pp}" if not pp.startswith("http") else pp
        if data.get("backdrop_path") and not content.backdrop_url:
            bp = data["backdrop_path"]
            content.backdrop_url = f"{backdrop_base}{bp}" if not bp.startswith("http") else bp
        if data.get("vote_average") and not content.rating:
            content.rating = data["vote_average"]
        if data.get("id") and "tmdb" not in known:
            known["tmdb"] = str(data["id"])
        content.updated_at = datetime.now(UTC)
        return known
