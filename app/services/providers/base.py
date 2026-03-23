"""
Abstract base for content providers and the normalised data container.
"""
from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class NormalizedContent:
    """Platform-agnostic representation of a movie or TV show."""

    title: str
    content_type: str                        # "movie" or "tv_show"
    source: str                              # "tmdb", "tvdb", "omdb", "tvmaze"

    description: Optional[str] = None
    release_date: Optional[str] = None       # YYYY-MM-DD (or YYYY)
    year: Optional[int] = None
    rating: Optional[float] = None
    poster_url: Optional[str] = None
    backdrop_url: Optional[str] = None
    genres: List[str] = field(default_factory=list)

    imdb_id: Optional[str] = None            # tt1234567
    tmdb_id: Optional[int] = None
    tvdb_id: Optional[int] = None
    tvmaze_id: Optional[int] = None

    runtime: Optional[int] = None            # minutes
    status: Optional[str] = None             # "Running", "Ended", …
    network: Optional[str] = None
    director: Optional[str] = None
    seasons: Optional[int] = None
    episodes: Optional[int] = None
    premiered: Optional[str] = None          # YYYY-MM-DD

    raw: Dict[str, Any] = field(default_factory=dict, repr=False)

    # ----- helpers used by dedup -----

    @property
    def dedup_key(self) -> str:
        """Lowercased, stripped key for fuzzy title+year matching."""
        norm = _normalise_title(self.title)
        y = self.year or _year_from_date(self.release_date)
        return f"{norm}::{y or ''}::{self.content_type}"

    def merge(self, other: NormalizedContent) -> None:
        """Fill in blanks from *other* without overwriting existing data."""
        for attr in (
            "description", "release_date", "year", "rating",
            "poster_url", "backdrop_url", "runtime", "status",
            "network", "director", "seasons", "episodes", "premiered",
            "imdb_id", "tmdb_id", "tvdb_id", "tvmaze_id",
        ):
            if getattr(self, attr) is None and getattr(other, attr) is not None:
                setattr(self, attr, getattr(other, attr))
        if not self.genres and other.genres:
            self.genres = other.genres


# ---- utility functions --------------------------------------------------- #

def _normalise_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^\w\s]", "", t).lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _year_from_date(d: Optional[str]) -> Optional[int]:
    if not d:
        return None
    m = re.match(r"(\d{4})", d)
    return int(m.group(1)) if m else None


class ContentProvider(ABC):
    """Interface that every content platform must implement."""

    name: str = "base"

    @abstractmethod
    def discover_movies(self, page: int = 1) -> List[NormalizedContent]:
        """Return a page of movies (browse/trending).  Empty list if unsupported."""
        ...

    @abstractmethod
    def discover_tv_shows(self, page: int = 1) -> List[NormalizedContent]:
        """Return a page of TV shows (browse/trending).  Empty list if unsupported."""
        ...

    @abstractmethod
    def search(self, query: str, content_type: Optional[str] = None) -> List[NormalizedContent]:
        """Search for content by title."""
        ...

    @abstractmethod
    def get_upcoming(self, content_type: str = "tv_show") -> List[NormalizedContent]:
        """Upcoming movies or episodes.  Empty list if unsupported."""
        ...

    def get_trending(self) -> List[NormalizedContent]:
        """Trending content.  Default implementation returns empty list."""
        return []
