"""
TMDb content provider — talks directly to the TMDb v3 API.

Without ``TMDB_API_KEY``, all methods return empty lists (TMDb is optional /
license-sensitive for commercial use).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings
from app.services.providers.base import ContentProvider, NormalizedContent, _year_from_date

logger = logging.getLogger(__name__)

BASE_URL = "https://api.themoviedb.org/3"
IMAGE_BASE_URL = "https://image.tmdb.org/t/p/w500"
BACKDROP_BASE_URL = "https://image.tmdb.org/t/p/original"


class TMDbProvider(ContentProvider):
    """Content provider for the TMDb v3 API."""

    name = "tmdb"

    def __init__(self) -> None:
        self._api_key = (settings.tmdb_api_key or "").strip()
        if not self._api_key:
            logger.warning("TMDB_API_KEY not set; TMDbProvider will return empty results")

    def _configured(self) -> bool:
        return bool(self._api_key)

    # ---- HTTP helpers ---- #

    def _get(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        if not self._api_key:
            return None
        base_params: dict[str, Any] = {"api_key": self._api_key, "language": "en-US"}
        if params:
            base_params.update(params)
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(f"{BASE_URL}/{endpoint}", params=base_params)
                resp.raise_for_status()
                return resp.json()
        except Exception as e:
            logger.error("TMDb API error (%s): %s", endpoint, e)
            return None

    def _format_poster(self, item: dict[str, Any]) -> dict[str, Any]:
        if item.get("poster_path"):
            item["poster_path"] = f"{IMAGE_BASE_URL}{item['poster_path']}"
        if item.get("backdrop_path"):
            item["backdrop_path"] = f"{BACKDROP_BASE_URL}{item['backdrop_path']}"
        return item

    def _fetch_results(self, endpoint: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        data = self._get(endpoint, params)
        if not data:
            return []
        return [self._format_poster(r) for r in data.get("results", []) if isinstance(r, dict)]

    # ---- normalisation ---- #

    def _normalize(self, item: dict[str, Any], content_type: str) -> NormalizedContent:
        release = item.get("release_date") or item.get("first_air_date")
        vote = item.get("vote_average")
        rating: float | None = None
        if vote is not None:
            try:
                rating = float(vote)
            except (TypeError, ValueError):
                rating = None

        genre_ids = item.get("genre_ids") or []
        genres = [str(gid) for gid in genre_ids]

        return NormalizedContent(
            title=(item.get("title") or item.get("name") or ""),
            content_type=content_type,
            source="tmdb",
            description=item.get("overview"),
            release_date=release if isinstance(release, str) else None,
            year=_year_from_date(release if isinstance(release, str) else None),
            rating=rating,
            poster_url=item.get("poster_path"),
            backdrop_url=item.get("backdrop_path"),
            tmdb_id=item.get("id"),
            genres=genres,
            raw=item,
        )

    def _normalize_list(self, items: list[dict[str, Any]], content_type: str) -> list[NormalizedContent]:
        return [self._normalize(i, content_type) for i in items if isinstance(i, dict)]

    # ---- ContentProvider interface ---- #

    def discover_movies(self, page: int = 1) -> list[NormalizedContent]:
        if not self._configured():
            return []
        raw = self._fetch_results(
            "discover/movie",
            {"sort_by": "popularity.desc", "page": page, "include_adult": "false"},
        )
        return self._normalize_list(raw, "movie")

    def discover_tv_shows(self, page: int = 1) -> list[NormalizedContent]:
        if not self._configured():
            return []
        raw = self._fetch_results(
            "discover/tv",
            {"sort_by": "popularity.desc", "page": page},
        )
        return self._normalize_list(raw, "tv_show")

    def search(self, query: str, content_type: str | None = None) -> list[NormalizedContent]:
        if not self._configured():
            return []
        out: list[NormalizedContent] = []

        def _search_type(ct: str) -> None:
            endpoint = "search/movie" if ct == "movie" else "search/tv"
            data = self._get(endpoint, {"query": query})
            if data and data.get("results"):
                hit = self._format_poster(data["results"][0])
                if isinstance(hit, dict):
                    out.append(self._normalize(hit, ct))

        if content_type == "movie":
            _search_type("movie")
        elif content_type in ("tv_show", "tv"):
            _search_type("tv_show")
        elif content_type is None:
            _search_type("movie")
            _search_type("tv_show")
        return out

    def get_upcoming(self, content_type: str = "tv_show") -> list[NormalizedContent]:
        if not self._configured():
            return []
        endpoint = "movie/upcoming" if content_type == "movie" else "tv/on_the_air"
        ct = "movie" if content_type == "movie" else "tv_show"
        raw = self._fetch_results(endpoint)
        return self._normalize_list(raw, ct)

    def get_trending(self) -> list[NormalizedContent]:
        if not self._configured():
            return []
        raw = self._fetch_results("trending/all/week")
        out: list[NormalizedContent] = []
        for item in raw:
            mt = item.get("media_type")
            if mt == "movie":
                out.append(self._normalize(item, "movie"))
            elif mt == "tv":
                out.append(self._normalize(item, "tv_show"))
        return out
