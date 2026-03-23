"""
TVMaze API content provider (TV shows only).
"""
from __future__ import annotations

import logging
import re
import time
from collections import deque
from typing import Any, Dict, List, Optional

import httpx

from app.config import settings
from app.services.providers.base import ContentProvider, NormalizedContent

logger = logging.getLogger(__name__)

BASE_URL = "https://api.tvmaze.com"
_RATE_WINDOW_SEC = 10.0
_RATE_MAX_CALLS = 20


def _strip_html(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    return re.sub(r"<[^>]+>", "", text).strip() or None


class TVMazeProvider(ContentProvider):
    """Content provider backed by the public TVMaze API."""

    name = "tvmaze"

    def __init__(self) -> None:
        self._client = httpx.Client(base_url=BASE_URL, timeout=15.0)
        self._call_times: deque[float] = deque()

    def __del__(self) -> None:
        try:
            self._client.close()
        except Exception:
            pass

    def _base_query(self) -> Dict[str, str]:
        if settings.tvmaze_api_key:
            return {"apikey": settings.tvmaze_api_key}
        return {}

    def _rate_limit(self) -> None:
        now = time.monotonic()
        while self._call_times and now - self._call_times[0] >= _RATE_WINDOW_SEC:
            self._call_times.popleft()
        if len(self._call_times) >= _RATE_MAX_CALLS:
            wait = _RATE_WINDOW_SEC - (now - self._call_times[0])
            if wait > 0:
                time.sleep(wait)
            now = time.monotonic()
            while self._call_times and now - self._call_times[0] >= _RATE_WINDOW_SEC:
                self._call_times.popleft()
        self._call_times.append(time.monotonic())

    def _get_json(self, path: str, **params: Any) -> Optional[Any]:
        self._rate_limit()
        q: Dict[str, Any] = {**self._base_query()}
        for k, v in params.items():
            if v is not None:
                q[k] = v
        try:
            resp = self._client.get(path, params=q)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPError as e:
            logger.warning("TVMaze HTTP error for %s: %s", path, e)
            return None
        except ValueError as e:
            logger.warning("TVMaze invalid JSON for %s: %s", path, e)
            return None

    def _normalize_show(self, show: Dict[str, Any]) -> NormalizedContent:
        summary = show.get("summary")
        desc = _strip_html(summary) if isinstance(summary, str) else None
        premiered = show.get("premiered")
        year: Optional[int] = None
        if premiered and isinstance(premiered, str):
            m = re.match(r"(\d{4})", premiered)
            if m:
                year = int(m.group(1))

        rating_block = show.get("rating") or {}
        rating = rating_block.get("average")
        if rating is not None:
            try:
                rating = float(rating)
            except (TypeError, ValueError):
                rating = None

        image = show.get("image") or {}
        poster = image.get("original") or image.get("medium")

        externals = show.get("externals") or {}
        imdb_raw = externals.get("imdb")
        imdb_id = str(imdb_raw) if imdb_raw is not None else None
        tvdb_raw = externals.get("thetvdb")
        tvdb_id: Optional[int] = None
        if tvdb_raw is not None:
            try:
                tvdb_id = int(tvdb_raw)
            except (TypeError, ValueError):
                tvdb_id = None

        network = show.get("network") or {}
        web_ch = show.get("webChannel") or {}
        net_name = network.get("name") or web_ch.get("name")

        runtime = show.get("runtime")
        if runtime is not None:
            try:
                runtime = int(runtime)
            except (TypeError, ValueError):
                runtime = None

        show_id = show.get("id")
        tvmaze_id: Optional[int] = None
        if show_id is not None:
            try:
                tvmaze_id = int(show_id)
            except (TypeError, ValueError):
                tvmaze_id = None

        title = show.get("name") or ""

        return NormalizedContent(
            title=title,
            content_type="tv_show",
            source="tvmaze",
            description=desc,
            release_date=premiered if isinstance(premiered, str) else None,
            year=year,
            rating=rating,
            poster_url=poster,
            genres=list(show.get("genres") or []),
            imdb_id=imdb_id,
            tvdb_id=tvdb_id,
            tvmaze_id=tvmaze_id,
            runtime=runtime,
            status=show.get("status"),
            network=net_name,
            premiered=premiered if isinstance(premiered, str) else None,
            raw=dict(show),
        )

    def discover_movies(self, page: int = 1) -> List[NormalizedContent]:
        return []

    def discover_tv_shows(self, page: int = 1) -> List[NormalizedContent]:
        try:
            data = self._get_json("/shows", page=page)
            if not isinstance(data, list):
                return []
            allowed_status = {"Running", "To Be Determined"}
            filtered: List[Dict[str, Any]] = []
            for s in data:
                if not isinstance(s, dict):
                    continue
                w = s.get("weight")
                try:
                    w_val = int(w) if w is not None else 0
                except (TypeError, ValueError):
                    w_val = 0
                if w_val < 70:
                    continue
                if s.get("status") not in allowed_status:
                    continue
                if s.get("language") != "English":
                    continue
                filtered.append(s)
            filtered.sort(key=lambda x: int(x.get("weight") or 0), reverse=True)
            return [self._normalize_show(s) for s in filtered]
        except Exception as e:
            logger.warning("discover_tv_shows failed: %s", e)
            return []

    def search(self, query: str, content_type: Optional[str] = None) -> List[NormalizedContent]:
        if content_type == "movie":
            return []
        try:
            data = self._get_json("/search/shows", q=query)
            if not isinstance(data, list):
                return []
            out: List[NormalizedContent] = []
            for row in data:
                if not isinstance(row, dict):
                    continue
                show = row.get("show")
                if isinstance(show, dict):
                    out.append(self._normalize_show(show))
            return out
        except Exception as e:
            logger.warning("search failed: %s", e)
            return []

    def get_upcoming(self, content_type: str = "tv_show") -> List[NormalizedContent]:
        if content_type == "movie":
            return []
        try:
            broadcast = self._get_json("/schedule", country="US")
            web = self._get_json("/schedule/web")
            if not isinstance(broadcast, list):
                broadcast = []
            if not isinstance(web, list):
                web = []
            by_id: Dict[int, Dict[str, Any]] = {}

            def _ingest_schedule(items: List[Any]) -> None:
                for block in items:
                    if not isinstance(block, dict):
                        continue
                    show = block.get("show")
                    if not isinstance(show, dict):
                        continue
                    sid = show.get("id")
                    try:
                        iid = int(sid)
                    except (TypeError, ValueError):
                        continue
                    if iid not in by_id:
                        by_id[iid] = show

            _ingest_schedule(broadcast)
            _ingest_schedule(web)
            return [self._normalize_show(s) for s in by_id.values()]
        except Exception as e:
            logger.warning("get_upcoming failed: %s", e)
            return []

    def get_trending(self) -> List[NormalizedContent]:
        try:
            data = self._get_json("/shows", page=0)
            if not isinstance(data, list):
                return []
            shows = [s for s in data if isinstance(s, dict)]

            def weight_key(s: Dict[str, Any]) -> int:
                w = s.get("weight")
                try:
                    return int(w) if w is not None else 0
                except (TypeError, ValueError):
                    return 0

            shows.sort(key=weight_key, reverse=True)
            top = shows[:20]
            return [self._normalize_show(s) for s in top]
        except Exception as e:
            logger.warning("get_trending failed: %s", e)
            return []
