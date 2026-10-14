"""
Content discovery service — aggregates results from all enabled providers,
deduplicates, and persists via ContentRepository.

Tracks per-provider page state so each run fetches the *next* batch of
content rather than re-scanning the same data.  Once a provider returns
an empty page the provider is marked ``fully_synced`` and subsequent runs
switch to "refresh mode" — fetching page 1, plus any pages past the last one
seen, to pick up newly-registered content on the source platform.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.orm import Session

from app.config import settings
from app.models.discovery_state import DiscoveryState
from app.repositories.content_repo import ContentRepository
from app.services.identity import ID_KINDS, Conflict, Identity, Match, id_keys, resolve
from app.services.providers.base import (
    ContentProvider,
    NormalizedContent,
    _normalise_title,
    _year_from_date,
    is_end_of_stream,
    is_explicit_end,
)
from app.services.providers.registry import get_active_providers
from app.services.refresh_planner import due_titles, failure_delay, success_delay
from app.services.review_list import park

logger = logging.getLogger(__name__)

SEED_PAGES = 5  # pages to fetch on first-ever run per provider


def _identity(nc: NormalizedContent) -> Identity:
    return Identity(
        title=nc.title,
        content_type=nc.content_type,
        year=nc.year or _year_from_date(nc.release_date),
        ids={kind: str(value) for kind in ID_KINDS if (value := getattr(nc, f"{kind}_id"))},
        ref=nc,
    )


def _deduplicate(
    items: list[NormalizedContent],
    on_conflict: Callable[[Identity, Conflict], None] | None = None,
) -> list[NormalizedContent]:
    """Merge duplicates across providers; the identity resolver decides what is the same title.

    Only the kept items that share an id or a title with the incoming one are shown to the
    resolver, so the pass stays linear. A conflict is never merged; with ``on_conflict`` it
    is also left out of the result and handed to that callback.
    """
    by_key: dict[tuple[Any, ...], list[Identity]] = {}
    result: list[NormalizedContent] = []

    for nc in items:
        incoming = _identity(nc)
        keys = [("id", *k) for k in id_keys(incoming)]
        title = _normalise_title(nc.title)
        if title:
            keys.append(("title", nc.content_type, title))
        candidates = [c for key in keys for c in by_key.get(key, [])]

        decision = resolve(incoming, candidates)
        if isinstance(decision, Match):
            decision.candidate.ref.merge(nc)
            continue
        if isinstance(decision, Conflict) and on_conflict is not None:
            on_conflict(incoming, decision)
            continue
        result.append(nc)
        for key in keys:
            by_key.setdefault(key, []).append(incoming)

    logger.info("Dedup: %d raw items → %d unique", len(items), len(result))
    return result


def _row_identity(row: Any, ids: dict[str, str]) -> Identity:
    """A stored title's identity; ``ids`` are its provider ids from the external-id table."""
    return Identity(
        title=row.title,
        content_type=row.content_type,
        year=_year_from_date(row.release_date),
        ids={kind: ids[kind] for kind in ID_KINDS if kind in ids},
        ref=row,
    )


class ContentDiscoveryService:
    def __init__(self, db: Session):
        self.repo = ContentRepository(db)
        self.db = db
        self.providers = get_active_providers()
        self._clock = time.monotonic
        self._deadline: float | None = None
        self._known_ids: dict[int, dict[str, str]] = {}  # content id -> {provider: id}, from the external-id table

    def _out_of_time(self) -> bool:
        return self._deadline is not None and self._clock() >= self._deadline

    # ---- state management ------------------------------------------------ #

    def _get_state(self, provider: str, content_type: str) -> DiscoveryState:
        state = self.db.query(DiscoveryState).filter_by(provider=provider, content_type=content_type).first()
        if not state:
            state = DiscoveryState(
                provider=provider,
                content_type=content_type,
                last_page=0,
                total_items_fetched=0,
                fully_synced=False,
            )
            self.db.add(state)
            self.db.flush()
        return state

    def _advance_state(self, state: DiscoveryState, items_fetched: int) -> None:
        state.last_page += 1
        state.total_items_fetched += items_fetched
        state.last_synced_at = datetime.now(UTC)

    def _mark_fully_synced(self, state: DiscoveryState) -> None:
        """Mark provider+content_type as fully synced (end of catalog reached)."""
        state.fully_synced = True
        state.last_synced_at = datetime.now(UTC)
        logger.info(
            "%s/%s fully synced at page %d (%d total items)",
            state.provider,
            state.content_type,
            state.last_page,
            state.total_items_fetched,
        )

    # ---- provider fetch with page progression ----------------------------- #

    def _fetch_from_provider(
        self,
        provider: ContentProvider,
        content_type: str,
        pages: int = 1,
    ) -> list[NormalizedContent]:
        """Fetch up to *pages* consecutive pages from a provider, advancing state.

        A fully-synced provider is still checked for new content: its first page
        (for sources that list the newest titles first) and any pages past the
        last one we saw (for sources that list oldest first and append new titles
        at the end, like TVDB).
        """
        state = self._get_state(provider.name, content_type)

        if state.fully_synced:
            refreshed = self._refresh_provider(provider, content_type, state)
            appended, _ = self._walk_pages(provider, content_type, state, pages)
            return refreshed + appended

        items, reached_end = self._walk_pages(provider, content_type, state, pages)
        if reached_end:
            self._mark_fully_synced(state)
        return items

    def _walk_pages(
        self,
        provider: ContentProvider,
        content_type: str,
        state: DiscoveryState,
        pages: int,
    ) -> tuple[list[NormalizedContent], bool]:
        """Read consecutive pages after ``state.last_page``; returns (items, reached_end).

        ``reached_end`` is True when an empty page was confirmed as the end: it came after
        pages with titles (in this walk or earlier ones, via the saved cursor), or the provider
        marked it as the end itself. An empty first page of a fresh walk is not enough, since
        a source that lists nothing usable would otherwise be called finished.
        """
        all_items: list[NormalizedContent] = []

        for _ in range(pages):
            if self._out_of_time():
                logger.info("%s: time budget reached for %s, resuming next run", provider.name, content_type)
                return all_items, False
            next_page = state.last_page + 1
            try:
                if content_type == "movie":
                    items = provider.discover_movies(page=next_page)
                else:
                    items = provider.discover_tv_shows(page=next_page)
            except Exception as e:
                logger.warning(
                    "%s page %d (%s) failed: %s",
                    provider.name,
                    next_page,
                    content_type,
                    e,
                )
                return all_items, False

            if is_end_of_stream(items):
                logger.info("%s: empty page %d for %s", provider.name, next_page, content_type)
                followed_pages = bool(all_items) or state.last_page > 0
                return all_items, followed_pages or is_explicit_end(items)
            if not items:
                logger.info("%s: page %d for %s had nothing usable, moving on", provider.name, next_page, content_type)
                self._advance_state(state, 0)
                continue

            logger.info(
                "%s: fetched %d %s items from page %d",
                provider.name,
                len(items),
                content_type,
                next_page,
            )
            all_items.extend(items)
            self._advance_state(state, len(items))

        return all_items, False

    def _refresh_provider(
        self,
        provider: ContentProvider,
        content_type: str,
        state: DiscoveryState,
    ) -> list[NormalizedContent]:
        """Fetch page 1 from a fully-synced provider to pick up new content."""
        try:
            if content_type == "movie":
                items = provider.discover_movies(page=1)
            else:
                items = provider.discover_tv_shows(page=1)
        except Exception as e:
            logger.warning("%s refresh (%s) failed: %s", provider.name, content_type, e)
            return []

        state.last_synced_at = datetime.now(UTC)
        if items:
            logger.info(
                "%s: refresh fetched %d %s items (page 1)",
                provider.name,
                len(items),
                content_type,
            )
        return items or []

    # ---- public API ------------------------------------------------------- #

    def is_catalog_empty(self) -> bool:
        from app.models.content import Content

        return self.db.query(Content.id).first() is None

    def seed_catalog(self) -> int:
        """First-run seeding: fetch several pages from each provider."""
        logger.info("Seeding catalog with %d pages per provider...", SEED_PAGES)
        total = 0
        total += self._discover("movie", pages=SEED_PAGES)
        total += self._discover("tv_show", pages=SEED_PAGES)
        return total

    def run_scheduled_sync(self, time_budget: float | None = None) -> dict[str, int]:
        """Called by the scheduler — uses configured batch_size.

        With *time_budget* (seconds), stops fetching pages once it is spent; what was
        fetched is saved together with the page cursor, so the next run continues.
        """
        self._deadline = self._clock() + time_budget if time_budget is not None else None
        try:
            batch = settings.discovery_batch_size
            movies = self._discover("movie", pages=batch)
            shows = self._discover("tv_show", pages=batch)
        finally:
            self._deadline = None
        return {"movies": movies, "tv_shows": shows}

    def run_full_sync(
        self,
        provider_name: str | None = None,
        max_pages: int = 500,
    ) -> dict[str, int]:
        """CLI-triggered exhaustive sync — page through until empty or max_pages."""
        movies = self._discover("movie", pages=max_pages, provider_filter=provider_name)
        shows = self._discover("tv_show", pages=max_pages, provider_filter=provider_name)
        return {"movies": movies, "tv_shows": shows}

    def run_n_pages(
        self,
        pages: int,
        provider_name: str | None = None,
    ) -> dict[str, int]:
        """CLI-triggered N-page sync."""
        movies = self._discover("movie", pages=pages, provider_filter=provider_name)
        shows = self._discover("tv_show", pages=pages, provider_filter=provider_name)
        return {"movies": movies, "tv_shows": shows}

    def _screen_stored(self, items: list[NormalizedContent]) -> list[NormalizedContent]:
        """Park titles whose ids point at several stored titles, or contradict the one they match."""
        kept: list[NormalizedContent] = []
        sharing = self.repo.stored_sharing_ids(items)
        known = self.repo.external_ids_for([row.id for rows in sharing for row in rows])
        for nc, rows in zip(items, sharing, strict=True):
            decision = resolve(_identity(nc), [_row_identity(r, known[r.id]) for r in rows]) if rows else None
            if isinstance(decision, Conflict):
                park(self.db, _identity(nc), decision)
            else:
                kept.append(nc)
        return kept

    def _fill_new_movie_release_dates(self, items: list[NormalizedContent]) -> None:
        """Give new movies a release date and poster before they are saved.

        TVDB's movie list omits the date, so a movie saved straight from the list
        has no date and sorts to the end. Only new titles are looked up; titles
        already in the catalogue are left to the enrichment job.
        """
        tvdb = next((p for p in self.providers if p.name == "tvdb" and hasattr(p, "get_movie_release")), None)
        if tvdb is None:
            return
        for nc in items:
            if nc.content_type != "movie" or nc.release_date or not nc.tvdb_id:
                continue
            if self.repo.get_by_tvdb_id(nc.tvdb_id, content_type="movie"):
                continue
            date, poster = tvdb.get_movie_release(nc.tvdb_id)
            if date:
                nc.release_date = date
                if date[:4].isdigit():
                    nc.year = int(date[:4])
            if poster and not nc.poster_url:
                nc.poster_url = poster

    def _discover(
        self,
        content_type: str,
        pages: int = 1,
        limit: int = 0,
        provider_filter: str | None = None,
    ) -> int:
        providers = self.providers
        if provider_filter:
            providers = [p for p in providers if p.name == provider_filter]
            if not providers:
                logger.warning("No active provider matching '%s'", provider_filter)
                return 0

        all_items: list[NormalizedContent] = []
        for provider in providers:
            items = self._fetch_from_provider(provider, content_type, pages=pages)
            all_items.extend(items)

        if not all_items:
            return 0

        deduped = self._screen_stored(_deduplicate(all_items, on_conflict=lambda i, c: park(self.db, i, c)))
        to_save = deduped[:limit] if limit > 0 else deduped
        self._fill_new_movie_release_dates(to_save)
        saved = self.repo.bulk_upsert_normalized(to_save)
        self.db.commit()
        logger.info(
            "%s discovery: saved %d items (from %d raw, %d deduped)",
            content_type,
            saved,
            len(all_items),
            len(deduped),
        )
        return saved

    def refresh_trending(self) -> int:
        all_items: list[NormalizedContent] = []
        for provider in self.providers:
            try:
                items = provider.get_trending()
                all_items.extend(items)
            except Exception as e:
                logger.warning("%s get_trending failed: %s", provider.name, e)

        deduped = _deduplicate(all_items)
        saved = self.repo.bulk_upsert_normalized(deduped)
        self.db.commit()
        return saved

    def search_all_providers(
        self, query: str, content_type: str | None = None, limit: int = 20
    ) -> list[NormalizedContent]:
        """Search all providers and return deduplicated results (not persisted)."""
        all_items: list[NormalizedContent] = []
        for provider in self.providers:
            try:
                items = provider.search(query, content_type)
                all_items.extend(items)
            except Exception as e:
                logger.warning("%s search failed: %s", provider.name, e)
        return _deduplicate(all_items)[:limit]

    # ---- detail enrichment ---- #

    def enrich_sparse_content(
        self,
        batch_size: int = 50,
        content_type: str | None = None,
        content_id: int | None = None,
        provider_filter: str | None = None,
        now: datetime | None = None,
    ) -> int:
        """Backfill missing detail data (runtime, episodes, language, etc.)
        on content records that have sparse information.

        Args:
            batch_size: Max records per run.
            content_type: Limit to ``"movie"`` or ``"tv_show"``.
            content_id: Enrich a single record by primary key.
            provider_filter: Only use this provider for detail/episode lookups.

        Returns the number of records enriched.
        """
        from app.models.content import Content
        from app.repositories.episode_repo import EpisodeRepository

        now = now or datetime.now(UTC)
        if content_id:
            target = self.db.query(Content).get(content_id)
            if not target:
                logger.warning("Content id %d not found", content_id)
                return 0
            sparse = [target]
        else:
            sparse = due_titles(self.db, batch_size, now, content_type)

        if not sparse:
            logger.info("No sparse content records to enrich")
            return 0

        providers = self.providers
        if provider_filter:
            providers = [p for p in providers if p.name == provider_filter]
            if not providers:
                logger.warning("No active provider matching '%s'", provider_filter)
                return 0

        ep_repo = EpisodeRepository(self.db)
        enriched = 0
        self._known_ids = self.repo.external_ids_for([c.id for c in sparse])

        for content in sparse:
            try:
                detail, detail_error = self._get_detail_with_error(content, providers)
                if detail:
                    self.repo._merge_into(content, detail, overwrite=True)

                if content.content_type == "tv_show":
                    episodes = self._get_episodes_for_content(content, providers)
                    if episodes:
                        count = ep_repo.bulk_upsert(content.id, episodes, overwrite=not content.refresh_locked)
                        if not content.episodes:
                            content.episodes = count
                        if not content.seasons:
                            content.seasons = ep_repo.get_season_count(content.id)

                if detail_error and not detail:
                    raise detail_error
                self._record_refresh_success(content, now)
                enriched += 1
                self.db.commit()
            except SoftTimeLimitExceeded:
                # Out of time, not the title's fault: what was finished is already committed.
                self.db.rollback()
                logger.warning("Enrichment out of time after %d record(s); the rest are due next run", enriched)
                break
            except Exception as e:
                self.db.rollback()
                logger.warning("Enrichment failed for %r: %s", content.title, e)
                self._record_refresh_failure(content.id, e, now)

        logger.info("Enriched %d content records", enriched)
        return enriched

    def _record_refresh_success(self, content, now: datetime) -> None:
        content.last_refreshed_at = now
        content.refresh_attempts = 0
        content.last_error = None
        content.next_refresh_at = now + success_delay(self.db, content.id, now)

    def _record_refresh_failure(self, content_id: int, error: Exception, now: datetime) -> None:
        """Keep the error and raise the attempt count; never let bookkeeping stop the run."""
        from app.models.content import Content

        try:
            row = self.db.get(Content, content_id)
            row.refresh_attempts = (row.refresh_attempts or 0) + 1
            row.last_error = f"{type(error).__name__}: {error}"[:2000]
            row.next_refresh_at = now + failure_delay(row.refresh_attempts)
            self.db.commit()
        except Exception:
            self.db.rollback()
            logger.exception("Could not record refresh failure for content %s", content_id)

    def count_sparse(self, content_type: str | None = None) -> dict:
        """Return counts of records that still need enrichment."""
        from app.models.content import Content

        q_tv = self.db.query(Content).filter(
            Content.content_type == "tv_show",
            Content.episodes.is_(None),
        )
        q_runtime = self.db.query(Content).filter(Content.runtime.is_(None))

        if content_type:
            q_tv = q_tv.filter(Content.content_type == content_type)
            q_runtime = q_runtime.filter(Content.content_type == content_type)

        return {
            "tv_missing_episodes": q_tv.count(),
            "missing_runtime": q_runtime.count(),
        }

    def _get_detail_for_content(self, content, providers: list | None = None) -> NormalizedContent | None:
        """Try each provider's get_details() using the matching external ID."""
        return self._get_detail_with_error(content, providers)[0]

    def _get_detail_with_error(
        self, content, providers: list | None = None
    ) -> tuple[NormalizedContent | None, Exception | None]:
        """Like _get_detail_for_content, but also returns the last provider error seen."""
        last_error: Exception | None = None
        for provider in providers or self.providers:
            try:
                ext_id = self._external_id_for(content, provider)
                if ext_id:
                    detail = provider.get_details(ext_id)
                    if detail:
                        return detail, None
            except SoftTimeLimitExceeded:
                raise
            except Exception as e:
                last_error = e
                logger.debug(
                    "%s get_details for %r failed: %s",
                    provider.name,
                    content.title,
                    e,
                )
        return None, last_error

    def _get_episodes_for_content(self, content, providers: list | None = None) -> list:
        """Try each provider's get_episodes() using the matching external ID."""
        for provider in providers or self.providers:
            try:
                ext_id = self._external_id_for(content, provider)
                if ext_id:
                    episodes = provider.get_episodes(ext_id)
                    if episodes:
                        return episodes
            except SoftTimeLimitExceeded:
                raise
            except Exception as e:
                logger.debug(
                    "%s get_episodes for %r failed: %s",
                    provider.name,
                    content.title,
                    e,
                )
        return []

    def _external_id_for(self, content, provider) -> str | None:
        """Return the appropriate external ID string for a given provider, from the external-id table."""
        wanted = {"tvmaze": "tvmaze", "tvdb": "tvdb", "omdb": "imdb"}.get(provider.name)
        if wanted is None:
            return None
        ids = self._known_ids.get(content.id)
        if ids is None:
            ids = self._known_ids[content.id] = self.repo.external_ids_for([content.id])[content.id]
        return ids.get(wanted)
