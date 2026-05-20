"""
Content discovery service — aggregates results from all enabled providers,
deduplicates, and persists via ContentRepository.

Tracks per-provider page state so each run fetches the *next* batch of
content rather than re-scanning the same data.  Once a provider returns
an empty page the provider is marked ``fully_synced`` and subsequent runs
switch to "refresh mode" — fetching page 1 to pick up newly-registered
content on the source platform.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.models.discovery_state import DiscoveryState
from app.repositories.content_repo import ContentRepository
from app.services.providers.base import ContentProvider, NormalizedContent
from app.services.providers.registry import get_active_providers

logger = logging.getLogger(__name__)

SEED_PAGES = 5  # pages to fetch on first-ever run per provider


def _deduplicate(items: list[NormalizedContent]) -> list[NormalizedContent]:
    """Merge duplicates across providers using external IDs then title+year."""
    by_imdb: dict[str, NormalizedContent] = {}
    by_tmdb: dict[int, NormalizedContent] = {}
    by_tvdb: dict[int, NormalizedContent] = {}
    by_tvmaze: dict[int, NormalizedContent] = {}
    by_key: dict[str, NormalizedContent] = {}
    result: list[NormalizedContent] = []

    for nc in items:
        existing: NormalizedContent | None = None

        if nc.imdb_id and nc.imdb_id in by_imdb:
            existing = by_imdb[nc.imdb_id]
        elif nc.tmdb_id and nc.tmdb_id in by_tmdb:
            existing = by_tmdb[nc.tmdb_id]
        elif nc.tvdb_id and nc.tvdb_id in by_tvdb:
            existing = by_tvdb[nc.tvdb_id]
        elif nc.tvmaze_id and nc.tvmaze_id in by_tvmaze:
            existing = by_tvmaze[nc.tvmaze_id]
        else:
            key = nc.dedup_key
            if key in by_key:
                existing = by_key[key]

        if existing:
            existing.merge(nc)
        else:
            result.append(nc)
            if nc.imdb_id:
                by_imdb[nc.imdb_id] = nc
            if nc.tmdb_id:
                by_tmdb[nc.tmdb_id] = nc
            if nc.tvdb_id:
                by_tvdb[nc.tvdb_id] = nc
            if nc.tvmaze_id:
                by_tvmaze[nc.tvmaze_id] = nc
            by_key[nc.dedup_key] = nc

    logger.info("Dedup: %d raw items → %d unique", len(items), len(result))
    return result


class ContentDiscoveryService:
    def __init__(self, db: Session):
        self.repo = ContentRepository(db)
        self.db = db
        self.providers = get_active_providers()

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
        """Fetch *pages* consecutive pages from a provider, advancing state."""
        state = self._get_state(provider.name, content_type)
        all_items: list[NormalizedContent] = []

        if state.fully_synced:
            return self._refresh_provider(provider, content_type, state)

        for _ in range(pages):
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
                break

            if not items:
                logger.info(
                    "%s: empty page %d for %s — marking fully synced",
                    provider.name,
                    next_page,
                    content_type,
                )
                self._mark_fully_synced(state)
                break

            logger.info(
                "%s: fetched %d %s items from page %d",
                provider.name,
                len(items),
                content_type,
                next_page,
            )
            all_items.extend(items)
            self._advance_state(state, len(items))

        return all_items

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

    def run_scheduled_sync(self) -> dict[str, int]:
        """Called by the scheduler — uses configured batch_size."""
        batch = settings.discovery_batch_size
        movies = self._discover("movie", pages=batch)
        shows = self._discover("tv_show", pages=batch)
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

        deduped = _deduplicate(all_items)
        to_save = deduped[:limit] if limit > 0 else deduped
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

        if content_id:
            target = self.db.query(Content).get(content_id)
            if not target:
                logger.warning("Content id %d not found", content_id)
                return 0
            sparse = [target]
        else:
            sparse = self._find_sparse(batch_size, content_type)

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

        for content in sparse:
            try:
                detail = self._get_detail_for_content(content, providers)
                if detail:
                    self.repo._merge_into(content, detail)

                if content.content_type == "tv_show":
                    episodes = self._get_episodes_for_content(content, providers)
                    if episodes:
                        count = ep_repo.bulk_upsert(content.id, episodes)
                        if not content.episodes:
                            content.episodes = count
                        if not content.seasons:
                            content.seasons = ep_repo.get_season_count(content.id)

                enriched += 1
                self.db.commit()
            except Exception as e:
                self.db.rollback()
                logger.warning("Enrichment failed for %r: %s", content.title, e)

        logger.info("Enriched %d content records", enriched)
        return enriched

    def _find_sparse(self, batch_size: int, content_type: str | None = None) -> list:
        """Return content records that need enrichment."""
        from app.models.content import Content

        # Priority 1: TV shows missing episode counts
        q = self.db.query(Content).filter(
            Content.content_type == "tv_show",
            Content.episodes.is_(None),
        )
        if content_type and content_type != "tv_show":
            q = q.filter(False)  # skip this tier if caller wants movies only
        sparse = q.order_by(Content.id).limit(batch_size).all()
        if sparse:
            return sparse

        # Priority 2: anything missing runtime
        q = self.db.query(Content).filter(Content.runtime.is_(None))
        if content_type:
            q = q.filter(Content.content_type == content_type)
        sparse = q.order_by(Content.id).limit(batch_size).all()
        return sparse

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
        for provider in providers or self.providers:
            try:
                ext_id = self._external_id_for(content, provider)
                if ext_id:
                    detail = provider.get_details(ext_id)
                    if detail:
                        return detail
            except Exception as e:
                logger.debug(
                    "%s get_details for %r failed: %s",
                    provider.name,
                    content.title,
                    e,
                )
        return None

    def _get_episodes_for_content(self, content, providers: list | None = None) -> list:
        """Try each provider's get_episodes() using the matching external ID."""
        for provider in providers or self.providers:
            try:
                ext_id = self._external_id_for(content, provider)
                if ext_id:
                    episodes = provider.get_episodes(ext_id)
                    if episodes:
                        return episodes
            except Exception as e:
                logger.debug(
                    "%s get_episodes for %r failed: %s",
                    provider.name,
                    content.title,
                    e,
                )
        return []

    @staticmethod
    def _external_id_for(content, provider) -> str | None:
        """Return the appropriate external ID string for a given provider."""
        if provider.name == "tvmaze" and content.tvmaze_id:
            return str(content.tvmaze_id)
        if provider.name == "tvdb" and content.tvdb_id:
            return str(content.tvdb_id)
        if provider.name == "omdb" and content.imdb_id:
            return content.imdb_id
        return None
