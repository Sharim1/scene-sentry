"""
OMDb API content provider (search + detail by IMDb ID).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Any

import httpx

from app.config import settings
from app.services.providers.base import ContentProvider, NormalizedContent

logger = logging.getLogger(__name__)

BASE_URL = "https://www.omdbapi.com/"


def _describe_error(exc: Exception) -> str:
    """Short, key-safe description of a failed request.

    An httpx error's text includes the full request URL, and OMDb takes the API
    key as a query parameter, so never log ``str(exc)``.
    """
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def _parse_year(year_val: Any) -> int | None:
    if year_val is None:
        return None
    s = str(year_val).strip()
    if not s or s.upper() == "N/A":
        return None
    m = re.match(r"(\d{4})", s)
    return int(m.group(1)) if m else None


def _parse_released(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.upper() == "N/A":
        return None
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return s


def _parse_rating(val: Any) -> float | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.upper() == "N/A":
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_runtime(val: Any) -> int | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.upper() == "N/A":
        return None
    m = re.search(r"\d+", s)
    return int(m.group(0)) if m else None


def _parse_seasons(val: Any) -> int | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.upper() == "N/A":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _na_or_str(val: Any) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    if not s or s.upper() == "N/A":
        return None
    return s


def _content_type_from_omdb_type(omdb_type: str) -> str:
    t = (omdb_type or "").lower()
    if t == "movie":
        return "movie"
    if t in ("series", "episode"):
        return "tv_show"
    return "movie"


def _normalize_omdb_dict(d: dict[str, Any]) -> NormalizedContent | None:
    title = _na_or_str(d.get("Title"))
    if not title:
        return None

    omdb_type = str(d.get("Type") or "")
    content_type = _content_type_from_omdb_type(omdb_type)

    plot = _na_or_str(d.get("Plot"))

    return NormalizedContent(
        title=title,
        content_type=content_type,
        provider="omdb",
        description=plot,
        year=_parse_year(d.get("Year")),
        release_date=_parse_released(d.get("Released")),
        rating=_parse_rating(d.get("imdbRating")),
        poster_url=_na_or_str(d.get("Poster")),
        genres=[g.strip() for g in str(d.get("Genre") or "").split(", ") if g.strip()]
        if _na_or_str(d.get("Genre"))
        else [],
        imdb_id=_na_or_str(d.get("imdbID")),
        runtime=_parse_runtime(d.get("Runtime")),
        director=_na_or_str(d.get("Director")),
        seasons=_parse_seasons(d.get("totalSeasons")),
        language=_na_or_str(d.get("Language")),
        country=_na_or_str(d.get("Country")),
        raw=dict(d),
    )


class OMDbProvider(ContentProvider):
    name = "omdb"

    def __init__(self) -> None:
        self._api_key = (settings.omdb_api_key or "").strip()
        self._client = httpx.Client(base_url=BASE_URL, timeout=15.0)
        if not self._api_key:
            logger.warning("OMDb API key is not set; OMDbProvider will return empty results")

    def discover_movies(self, page: int = 1) -> list[NormalizedContent]:
        return []

    def discover_tv_shows(self, page: int = 1) -> list[NormalizedContent]:
        return []

    def get_upcoming(self, content_type: str = "tv_show") -> list[NormalizedContent]:
        return []

    def search(self, query: str, content_type: str | None = None) -> list[NormalizedContent]:
        if not self._api_key:
            return []
        q = (query or "").strip()
        if not q:
            return []

        params: dict[str, Any] = {"apikey": self._api_key, "s": q, "page": 1}
        if content_type == "movie":
            params["type"] = "movie"
        elif content_type == "tv_show":
            params["type"] = "series"

        try:
            resp = self._client.get("/", params=params)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.debug("OMDb search failed: %s", _describe_error(exc))
            return []

        if not isinstance(data, dict) or data.get("Response") == "False":
            return []

        items = data.get("Search")
        if not isinstance(items, list):
            return []

        out: list[NormalizedContent] = []
        for item in items:
            if isinstance(item, dict):
                norm = _normalize_omdb_dict(item)
                if norm is not None:
                    out.append(norm)
        return out

    def get_details(self, imdb_id: str) -> NormalizedContent | None:
        if not self._api_key:
            return None
        iid = (imdb_id or "").strip()
        if not iid:
            return None

        params = {"apikey": self._api_key, "i": iid, "plot": "short"}
        try:
            resp = self._client.get("/", params=params)
            resp.raise_for_status()
            data = resp.json()
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.debug("OMDb get_details failed: %s", _describe_error(exc))
            return None

        if not isinstance(data, dict) or data.get("Response") == "False":
            return None

        return _normalize_omdb_dict(data)
