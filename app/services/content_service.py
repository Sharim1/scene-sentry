"""
Content service for TMDb API
"""

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class TMDbService:
    """Service for interacting with TMDb API"""

    BASE_URL = "https://api.themoviedb.org/3"
    IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
    BACKDROP_BASE_URL = "https://image.tmdb.org/t/p/original"

    def __init__(self):
        self.api_key = settings.tmdb_api_key
        if not self.api_key:
            logger.warning("TMDB_API_KEY not found, TMDb features will be limited")

    def _get(self, endpoint: str, params: dict | None = None) -> dict | None:
        if not self.api_key:
            return None
        base_params = {"api_key": self.api_key, "language": "en-US"}
        if params:
            base_params.update(params)
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(f"{self.BASE_URL}/{endpoint}", params=base_params)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error(f"TMDb API error ({endpoint}): {e}")
            return None

    def _format_poster(self, item: dict) -> dict:
        if item.get("poster_path"):
            item["poster_path"] = f"{self.IMAGE_BASE_URL}{item['poster_path']}"
        if item.get("backdrop_path"):
            item["backdrop_path"] = f"{self.BACKDROP_BASE_URL}{item['backdrop_path']}"
        return item

    def _format_results(self, data: dict | None) -> list[dict[str, Any]]:
        if not data:
            return []
        results = data.get("results", [])
        return [self._format_poster(r) for r in results]

    # --- Search ---

    def search_content(self, title: str, content_type: str) -> dict[str, Any] | None:
        endpoint = "search/movie" if content_type == "movie" else "search/tv"
        data = self._get(endpoint, {"query": title})
        if data and data.get("results"):
            return self._format_poster(data["results"][0])
        return None

    def get_content_details(self, tmdb_id: int, content_type: str) -> dict[str, Any] | None:
        endpoint = "movie" if content_type == "movie" else "tv"
        data = self._get(f"{endpoint}/{tmdb_id}")
        return self._format_poster(data) if data else None

    # --- Discover ---

    def discover_movies(
        self,
        genre_ids: str | None = None,
        sort_by: str = "popularity.desc",
        year: int | None = None,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        params: dict = {"sort_by": sort_by, "page": page, "include_adult": "false"}
        if genre_ids:
            params["with_genres"] = genre_ids
        if year:
            params["primary_release_year"] = year
        return self._format_results(self._get("discover/movie", params))

    def discover_tv_shows(
        self,
        genre_ids: str | None = None,
        sort_by: str = "popularity.desc",
        page: int = 1,
    ) -> list[dict[str, Any]]:
        params: dict = {"sort_by": sort_by, "page": page}
        if genre_ids:
            params["with_genres"] = genre_ids
        return self._format_results(self._get("discover/tv", params))

    # --- Trending ---

    def get_trending(self, media_type: str = "all", time_window: str = "week") -> list[dict[str, Any]]:
        return self._format_results(self._get(f"trending/{media_type}/{time_window}"))

    # --- Upcoming ---

    def get_upcoming(self, content_type: str = "movie") -> list[dict[str, Any]]:
        endpoint = "movie/upcoming" if content_type == "movie" else "tv/on_the_air"
        return self._format_results(self._get(endpoint))

    # --- Genres ---

    def get_genres(self, media_type: str = "movie") -> list[dict[str, Any]]:
        endpoint = f"genre/{media_type}/list"
        data = self._get(endpoint)
        return data.get("genres", []) if data else []
