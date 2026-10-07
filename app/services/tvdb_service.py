"""
TVDB service for TV show episode-level data
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


class TVDBService:
    """Service for interacting with the TVDB v4 API."""

    def __init__(self):
        self.client = None
        self._init_client()

    def _init_client(self):
        from app.config import settings

        api_key = getattr(settings, "tvdb_api_key", None)
        if not api_key:
            logger.warning("TVDB_API_KEY not configured, TVDB features disabled")
            return
        try:
            import tvdb_v4_official

            self.client = tvdb_v4_official.TVDB(api_key)
            logger.info("TVDBService initialised")
        except ImportError:
            logger.warning("tvdb_v4_official not installed – TVDB features disabled")
        except Exception as e:
            logger.error(f"Failed to initialise TVDB client: {e}")

    def search_series(self, name: str) -> list[dict[str, Any]]:
        if not self.client:
            return []
        try:
            results = self.client.search(name, type="series")
            return results or []
        except Exception as e:
            logger.error(f"TVDB search error: {e}")
            return []

    def get_series_details(self, series_id: int) -> dict[str, Any] | None:
        if not self.client:
            return None
        try:
            return self.client.get_series(series_id)
        except Exception as e:
            logger.error(f"TVDB series detail error: {e}")
            return None

    def get_series_episodes(self, series_id: int, season: int = 0) -> list[dict[str, Any]]:
        if not self.client:
            return []
        try:
            data = self.client.get_series_episodes(series_id, season_type="default")
            return data.get("episodes", []) if isinstance(data, dict) else []
        except Exception as e:
            logger.error(f"TVDB episodes error: {e}")
            return []

    def get_upcoming_episodes(self, series_ids: list[int]) -> list[dict[str, Any]]:
        """Return episodes with future air dates for the given series."""
        from datetime import date

        upcoming: list[dict[str, Any]] = []
        today = date.today().isoformat()
        for sid in series_ids:
            episodes = self.get_series_episodes(sid)
            for ep in episodes:
                air_date = ep.get("aired") or ""
                if air_date >= today:
                    ep["series_id"] = sid
                    upcoming.append(ep)
        return sorted(upcoming, key=lambda e: e.get("aired", ""))
