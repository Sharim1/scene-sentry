"""
Content repository - database access for Content model.

Supports multi-provider upsert with deduplication via external IDs and
title+year matching.
"""

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.content import Content
from app.services.providers.base import NormalizedContent

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


def _ids_conflict(row: Content, nc: NormalizedContent) -> bool:
    """True if the row and the incoming item carry the same kind of external id with
    different values: they are then different titles even if name and year match."""
    return any(
        getattr(row, attr) is not None and getattr(nc, attr) is not None and getattr(row, attr) != getattr(nc, attr)
        for attr in ("tvdb_id", "tmdb_id", "imdb_id", "tvmaze_id")
    )


class ContentRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- single-row lookups ---- #

    def get_by_id(self, content_id: int) -> Content | None:
        return self.db.query(Content).filter(Content.id == content_id).first()

    def get_by_imdb_id(self, imdb_id: str) -> Content | None:
        return self.db.query(Content).filter(Content.imdb_id == imdb_id).first()

    def get_by_tmdb_id(self, tmdb_id: int, content_type: str | None = None) -> Content | None:
        return self._first_by_numeric_id(Content.tmdb_id, tmdb_id, content_type)

    def get_by_tvdb_id(self, tvdb_id: int, content_type: str | None = None) -> Content | None:
        return self._first_by_numeric_id(Content.tvdb_id, tvdb_id, content_type)

    def get_by_tvmaze_id(self, tvmaze_id: int, content_type: str | None = None) -> Content | None:
        return self._first_by_numeric_id(Content.tvmaze_id, tvmaze_id, content_type)

    def _first_by_numeric_id(self, column: Any, value: int, content_type: str | None) -> Content | None:
        """Movies and series are numbered separately by TVDB and TMDb, so a numeric id
        only identifies a title within its own type; pass ``content_type`` to say which."""
        query = self.db.query(Content).filter(column == value)
        if content_type:
            query = query.filter(Content.content_type == content_type)
        return query.first()

    def get_by_title_year_type(self, title: str, year: int | None, content_type: str) -> Content | None:
        return next(iter(self._all_by_title_year_type(title, year, content_type)), None)

    def _all_by_title_year_type(self, title: str, year: int | None, content_type: str) -> list[Content]:
        q = self.db.query(Content).filter(
            Content.title == title,
            Content.content_type == content_type,
        )
        if year:
            q = q.filter(Content.release_date.like(f"{year}%"))
        return q.all()

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
        for candidate in self._all_by_title_year_type(nc.title, nc.year, nc.content_type):
            if not _ids_conflict(candidate, nc):
                return candidate
        return None

    def upsert_normalized(self, nc: NormalizedContent) -> Content:
        """Insert or merge a NormalizedContent into the DB, deduplicating."""
        existing = self.find_existing(nc)
        if existing:
            self._merge_into(existing, nc)
            return existing

        content = Content(
            title=nc.title[:200],
            content_type=nc.content_type,
            description=(nc.description or "")[:500] or None,
            genres=json.dumps(nc.genres) if nc.genres else None,
            imdb_id=nc.imdb_id,
            tmdb_id=nc.tmdb_id,
            tvdb_id=nc.tvdb_id,
            tvmaze_id=nc.tvmaze_id,
            poster_url=nc.poster_url,
            backdrop_url=nc.backdrop_url,
            release_date=nc.release_date,
            runtime=nc.runtime,
            rating=nc.rating,
            director=nc.director,
            seasons=nc.seasons,
            episodes=nc.episodes,
            status=nc.status,
            network=nc.network,
            provider=nc.provider,
            language=nc.language,
            country=nc.country,
            premiere_date=_parse_datetime(nc.premiered),
            next_episode_date=_parse_datetime(nc.next_episode_date),
        )
        self.db.add(content)
        self.db.flush()
        return content

    def bulk_upsert_normalized(self, items: list[NormalizedContent]) -> int:
        """Upsert a list of NormalizedContent items. Returns count saved."""
        count = 0
        for nc in items:
            try:
                self.upsert_normalized(nc)
                count += 1
            except Exception as e:
                logger.warning("Failed to upsert %r: %s", nc.title, e)
        return count

    # Legacy method kept for backward compat with old TMDB-dict ingestion
    def upsert_from_api(self, data: dict[str, Any], content_type: str) -> Content:
        tmdb_id = data.get("id")
        existing = self.get_by_tmdb_id(tmdb_id, content_type) if tmdb_id else None
        title = data.get("title") or data.get("name", "")
        if not existing:
            existing = self.get_by_title_year_type(title, None, content_type)
        if existing:
            self._update_from_api(existing, data, content_type)
            return existing
        content = self._create_from_api(data, content_type)
        self.db.add(content)
        self.db.flush()
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

    def _merge_into(self, content: Content, nc: NormalizedContent) -> None:
        """Fill blanks on an existing row from a NormalizedContent."""
        embedding_input_changed = False
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
        if nc.imdb_id and not content.imdb_id:
            content.imdb_id = nc.imdb_id
        if nc.tmdb_id and not content.tmdb_id:
            content.tmdb_id = nc.tmdb_id
        if nc.tvdb_id and not content.tvdb_id:
            content.tvdb_id = nc.tvdb_id
        if nc.tvmaze_id and not content.tvmaze_id:
            content.tvmaze_id = nc.tvmaze_id
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
            tmdb_id=data.get("id"),
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

    def _update_from_api(self, content: Content, data: dict[str, Any], content_type: str):
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
        if data.get("id") and not content.tmdb_id:
            content.tmdb_id = data["id"]
        content.updated_at = datetime.now(UTC)
