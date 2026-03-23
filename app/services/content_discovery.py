"""
Content discovery service — aggregates results from all enabled providers,
deduplicates, and persists via ContentRepository.

Tracks per-provider page state so each run fetches the *next* page of
content rather than re-scanning the same first page endlessly.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.discovery_state import DiscoveryState
from app.repositories.content_repo import ContentRepository
from app.services.providers.base import ContentProvider, NormalizedContent
from app.services.providers.registry import get_active_providers

logger = logging.getLogger(__name__)

SEED_PAGES = 3   # pages to fetch on first-ever run per provider


def _deduplicate(items: List[NormalizedContent]) -> List[NormalizedContent]:
    """Merge duplicates across providers using external IDs then title+year."""
    by_imdb: Dict[str, NormalizedContent] = {}
    by_tmdb: Dict[int, NormalizedContent] = {}
    by_tvdb: Dict[int, NormalizedContent] = {}
    by_tvmaze: Dict[int, NormalizedContent] = {}
    by_key: Dict[str, NormalizedContent] = {}
    result: List[NormalizedContent] = []

    for nc in items:
        existing: Optional[NormalizedContent] = None

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
        state = (
            self.db.query(DiscoveryState)
            .filter_by(provider=provider, content_type=content_type)
            .first()
        )
        if not state:
            state = DiscoveryState(
                provider=provider, content_type=content_type, last_page=0, total_items_fetched=0
            )
            self.db.add(state)
            self.db.flush()
        return state

    def _advance_state(self, state: DiscoveryState, items_fetched: int) -> None:
        state.last_page += 1
        state.total_items_fetched += items_fetched
        state.last_synced_at = datetime.now(timezone.utc)

    def _reset_state(self, state: DiscoveryState) -> None:
        """Reset to page 0 when a provider returns an empty page (end of catalog)."""
        state.last_page = 0
        state.last_synced_at = datetime.now(timezone.utc)

    # ---- provider fetch with page progression ----------------------------- #

    def _fetch_from_provider(
        self,
        provider: ContentProvider,
        content_type: str,
        pages: int = 1,
    ) -> List[NormalizedContent]:
        """Fetch *pages* consecutive pages from a provider, advancing state."""
        state = self._get_state(provider.name, content_type)
        all_items: List[NormalizedContent] = []

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
                    provider.name, next_page, content_type, e,
                )
                break

            if not items:
                logger.info(
                    "%s: empty page %d for %s — resetting to page 0",
                    provider.name, next_page, content_type,
                )
                self._reset_state(state)
                break

            logger.info(
                "%s: fetched %d %s items from page %d",
                provider.name, len(items), content_type, next_page,
            )
            all_items.extend(items)
            self._advance_state(state, len(items))

        return all_items

    # ---- public API ------------------------------------------------------- #

    def is_catalog_empty(self) -> bool:
        from app.models.content import Content
        return self.db.query(Content.id).first() is None

    async def seed_catalog(self) -> int:
        """First-run seeding: fetch several pages from each provider."""
        logger.info("Seeding catalog with %d pages per provider...", SEED_PAGES)
        total = 0
        total += await self._discover("movie", pages=SEED_PAGES)
        total += await self._discover("tv_show", pages=SEED_PAGES)
        return total

    async def discover_and_save_movies(
        self, preferences: Optional[str] = None, limit: int = 100
    ) -> int:
        return await self._discover("movie", pages=1, limit=limit)

    async def discover_and_save_tv_shows(
        self, preferences: Optional[str] = None, limit: int = 100
    ) -> int:
        return await self._discover("tv_show", pages=1, limit=limit)

    async def _discover(
        self, content_type: str, pages: int = 1, limit: int = 200
    ) -> int:
        all_items: List[NormalizedContent] = []
        for provider in self.providers:
            items = self._fetch_from_provider(provider, content_type, pages=pages)
            all_items.extend(items)

        if not all_items:
            return 0

        deduped = _deduplicate(all_items)
        saved = self.repo.bulk_upsert_normalized(deduped[:limit])
        self.db.commit()
        logger.info(
            "%s discovery: saved %d items (from %d raw, %d deduped)",
            content_type, saved, len(all_items), len(deduped),
        )
        return saved

    async def refresh_trending(self) -> int:
        all_items: List[NormalizedContent] = []
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

    async def search_all_providers(
        self, query: str, content_type: Optional[str] = None, limit: int = 20
    ) -> List[NormalizedContent]:
        """Search all providers and return deduplicated results (not persisted)."""
        all_items: List[NormalizedContent] = []
        for provider in self.providers:
            try:
                items = provider.search(query, content_type)
                all_items.extend(items)
            except Exception as e:
                logger.warning("%s search failed: %s", provider.name, e)
        return _deduplicate(all_items)[:limit]
