"""
TVDB v4 API content provider (movies and TV shows).

Uses the tvdb_v4_official SDK.  List endpoints for discovery, extended
endpoints for detail enrichment + episodes.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

from app.config import settings
from app.services.providers.base import (
    ContentProvider,
    NormalizedContent,
    NormalizedEpisode,
    _year_from_date,
)

logger = logging.getLogger(__name__)

_ARTWORKS_BASE = "https://artworks.thetvdb.com"


# ---- helper functions ---- #

def _parse_year(item: Dict[str, Any]) -> Optional[int]:
    y = item.get("year")
    if y is not None and str(y).strip():
        m = re.match(r"(\d{4})", str(y).strip())
        if m:
            return int(m.group(1))
    return _year_from_date(item.get("first_air_time")) or _year_from_date(
        item.get("firstAired")
    )


def _release_date(item: Dict[str, Any]) -> Optional[str]:
    return item.get("first_air_time") or item.get("firstAired")


def _poster_url(item: Dict[str, Any]) -> Optional[str]:
    iu = item.get("image_url")
    if iu and str(iu).startswith(("http://", "https://")):
        return str(iu)
    img = item.get("image")
    if not img:
        return None
    s = str(img)
    if s.startswith(("http://", "https://")):
        return s
    if s.startswith("/"):
        return f"{_ARTWORKS_BASE}{s}"
    return f"{_ARTWORKS_BASE}/banners/{s.lstrip('/')}"


def _status_value(item: Dict[str, Any]) -> Optional[str]:
    st = item.get("status")
    if st is None:
        return None
    if isinstance(st, dict):
        name = st.get("name")
        return str(name) if name is not None else None
    return str(st) if st else None


def _imdb_from_remote_ids(item: Dict[str, Any]) -> Optional[str]:
    for rid in item.get("remote_ids") or item.get("remoteIds") or []:
        if not isinstance(rid, dict):
            continue
        if rid.get("type") == 2:
            iid = rid.get("id")
            if iid:
                return str(iid).strip() or None
        src = rid.get("sourceName") or rid.get("source_name")
        if src and str(src).upper() == "IMDB":
            iid = rid.get("id")
            if iid:
                return str(iid).strip() or None
    return None


def _tvdb_id_value(item: Dict[str, Any]) -> Optional[int]:
    raw = item.get("tvdb_id")
    if raw is None:
        raw = item.get("id")
    if raw is None:
        oid = item.get("objectID")
        if isinstance(oid, str) and oid.strip():
            raw = oid.strip()
    if raw is None:
        return None
    try:
        return int(str(raw).split("-")[-1])
    except (TypeError, ValueError):
        return None


def _genres_list(item: Dict[str, Any]) -> List[str]:
    g = item.get("genres")
    if not g:
        return []
    out: List[str] = []
    for x in g:
        if isinstance(x, str):
            if x.strip():
                out.append(x.strip())
        elif isinstance(x, dict):
            n = x.get("name")
            if n and str(n).strip():
                out.append(str(n).strip())
    return out


def _safe_int(val: Any) -> Optional[int]:
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _normalize_search_result(item: Dict[str, Any], content_type: str) -> NormalizedContent:
    title = (item.get("name") or "").strip() or "Unknown"
    rd = _release_date(item)

    runtime = _safe_int(item.get("runtime") or item.get("averageRuntime"))
    language = item.get("originalLanguage")
    country = item.get("originalCountry")
    next_aired = item.get("nextAired")

    return NormalizedContent(
        title=title,
        content_type=content_type,
        source="tvdb",
        description=item.get("overview"),
        year=_parse_year(item),
        release_date=rd,
        poster_url=_poster_url(item),
        imdb_id=_imdb_from_remote_ids(item),
        tvdb_id=_tvdb_id_value(item),
        status=_status_value(item),
        network=item.get("network"),
        genres=_genres_list(item),
        runtime=runtime,
        language=language,
        country=country,
        next_episode_date=next_aired if next_aired else None,
        raw=dict(item),
    )


def _as_item_list(data: Any) -> List[Dict[str, Any]]:
    if not data:
        return []
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        inner = data.get("data") or data.get("results")
        if isinstance(inner, list):
            return [x for x in inner if isinstance(x, dict)]
    return []


def _normalize_tvdb_episode(ep: Dict[str, Any]) -> Optional[NormalizedEpisode]:
    season = _safe_int(ep.get("seasonNumber"))
    number = _safe_int(ep.get("number"))
    if season is None or number is None:
        return None
    return NormalizedEpisode(
        title=ep.get("name") or "",
        season_number=season,
        episode_number=number,
        description=ep.get("overview"),
        air_date=ep.get("aired"),
        runtime=_safe_int(ep.get("runtime")),
        tvdb_id=_safe_int(ep.get("id")),
    )


class TVDBProvider(ContentProvider):
    """Content provider backed by TheTVDB v4 API via tvdb_v4_official."""

    name = "tvdb"

    def __init__(self) -> None:
        self.client: Any = None
        api_key = getattr(settings, "tvdb_api_key", None)
        if not api_key:
            logger.warning("TVDB_API_KEY not configured; TVDBProvider disabled")
            return
        try:
            import tvdb_v4_official

            self.client = tvdb_v4_official.TVDB(api_key)
            logger.info("TVDBProvider initialised")
        except ImportError:
            logger.warning("tvdb_v4_official not installed; TVDBProvider disabled")
        except Exception as e:
            logger.warning("TVDBProvider could not initialise client: %s", e)
            self.client = None

    def discover_movies(self, page: int = 1) -> List[NormalizedContent]:
        if not self.client:
            return []
        try:
            raw = self.client.get_all_movies(page=max(0, page - 1))
            return [
                _normalize_search_result(it, "movie") for it in _as_item_list(raw)
            ]
        except Exception as e:
            logger.warning("TVDB discover_movies failed: %s", e)
            return []

    def discover_tv_shows(self, page: int = 1) -> List[NormalizedContent]:
        if not self.client:
            return []
        try:
            raw = self.client.get_all_series(page=max(0, page - 1))
            return [
                _normalize_search_result(it, "tv_show") for it in _as_item_list(raw)
            ]
        except Exception as e:
            logger.warning("TVDB discover_tv_shows failed: %s", e)
            return []

    def search(
        self, query: str, content_type: Optional[str] = None
    ) -> List[NormalizedContent]:
        if not self.client:
            return []
        q = (query or "").strip()
        if not q:
            return []
        out: List[NormalizedContent] = []
        try:
            if content_type == "movie":
                raw = self.client.search(q, type="movie")
                for it in _as_item_list(raw):
                    out.append(_normalize_search_result(it, "movie"))
            elif content_type == "tv_show":
                raw = self.client.search(q, type="series")
                for it in _as_item_list(raw):
                    out.append(_normalize_search_result(it, "tv_show"))
            else:
                for ctype, api_type in (
                    ("movie", "movie"),
                    ("tv_show", "series"),
                ):
                    raw = self.client.search(q, type=api_type)
                    for it in _as_item_list(raw):
                        out.append(_normalize_search_result(it, ctype))
        except Exception as e:
            logger.warning("TVDB search failed: %s", e)
            return []
        return out

    def get_upcoming(self, content_type: str = "tv_show") -> List[NormalizedContent]:
        return []

    # ---- detail + episode enrichment ---- #

    def get_details(self, external_id: str) -> Optional[NormalizedContent]:
        """Fetch extended series/movie detail by TVDB ID."""
        if not self.client:
            return None
        try:
            tvdb_id = int(external_id)
        except (TypeError, ValueError):
            return None

        try:
            raw = self.client.get_series_extended(tvdb_id)
            item = raw if isinstance(raw, dict) else {}
            if not item:
                return None
            return _normalize_search_result(item, "tv_show")
        except Exception as e:
            logger.warning("TVDB get_details(%s) failed: %s", external_id, e)
            return None

    def get_episodes(self, external_id: str) -> List[NormalizedEpisode]:
        """Fetch all episodes for a series by TVDB ID."""
        if not self.client:
            return []
        try:
            tvdb_id = int(external_id)
        except (TypeError, ValueError):
            return []

        all_eps: List[NormalizedEpisode] = []
        page = 0
        while True:
            try:
                raw = self.client.get_series_episodes(tvdb_id, page=page)
                items = _as_item_list(raw.get("episodes") if isinstance(raw, dict) else raw)
                if not items:
                    break
                for ep_data in items:
                    ne = _normalize_tvdb_episode(ep_data)
                    if ne is not None:
                        all_eps.append(ne)
                page += 1
            except Exception as e:
                logger.warning("TVDB get_episodes(%s) page %d failed: %s", external_id, page, e)
                break
        return all_eps
