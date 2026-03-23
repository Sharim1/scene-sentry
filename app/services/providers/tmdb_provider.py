"""
TMDb content provider — wraps TMDbService behind ContentProvider.

Without ``TMDB_API_KEY``, all methods return empty lists (TMDb is optional /
license-sensitive for commercial use).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.content_service import TMDbService
from app.services.providers.base import ContentProvider, NormalizedContent, _year_from_date


class TMDbProvider(ContentProvider):
    """Content provider delegating to TMDbService."""

    name = "tmdb"

    def __init__(self) -> None:
        self.tmdb = TMDbService()

    def _configured(self) -> bool:
        return bool(settings.tmdb_api_key)

    def _normalize(self, item: Dict[str, Any], content_type: str) -> NormalizedContent:
        release = item.get("release_date") or item.get("first_air_date")
        vote = item.get("vote_average")
        rating: Optional[float] = None
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

    def _normalize_list(self, items: List[Dict[str, Any]], content_type: str) -> List[NormalizedContent]:
        return [self._normalize(i, content_type) for i in items if isinstance(i, dict)]

    def discover_movies(self, page: int = 1) -> List[NormalizedContent]:
        if not self._configured():
            return []
        raw = self.tmdb.discover_movies(page=page)
        return self._normalize_list(raw, "movie")

    def discover_tv_shows(self, page: int = 1) -> List[NormalizedContent]:
        if not self._configured():
            return []
        raw = self.tmdb.discover_tv_shows(page=page)
        return self._normalize_list(raw, "tv_show")

    def search(self, query: str, content_type: Optional[str] = None) -> List[NormalizedContent]:
        if not self._configured():
            return []
        out: List[NormalizedContent] = []

        def run_movie() -> None:
            hit = self.tmdb.search_content(query, "movie")
            if hit and isinstance(hit, dict):
                out.append(self._normalize(hit, "movie"))

        def run_tv() -> None:
            hit = self.tmdb.search_content(query, "tv_show")
            if hit and isinstance(hit, dict):
                out.append(self._normalize(hit, "tv_show"))

        if content_type == "movie":
            run_movie()
        elif content_type in ("tv_show", "tv"):
            run_tv()
        elif content_type is None:
            run_movie()
            run_tv()
        return out

    def get_upcoming(self, content_type: str = "tv_show") -> List[NormalizedContent]:
        if not self._configured():
            return []
        raw = self.tmdb.get_upcoming(content_type)
        ct = "movie" if content_type == "movie" else "tv_show"
        return self._normalize_list(raw, ct)

    def get_trending(self) -> List[NormalizedContent]:
        if not self._configured():
            return []
        raw = self.tmdb.get_trending("all", "week")
        out: List[NormalizedContent] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            mt = item.get("media_type")
            if mt == "movie":
                out.append(self._normalize(item, "movie"))
            elif mt == "tv":
                out.append(self._normalize(item, "tv_show"))
        return out
