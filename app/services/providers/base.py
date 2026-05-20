"""
Abstract base for content providers and the normalised data container.
"""

from __future__ import annotations

import re
import unicodedata
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class NormalizedContent:
    """Platform-agnostic representation of a movie or TV show."""

    title: str
    content_type: str  # "movie" or "tv_show"
    source: str  # "tmdb", "tvdb", "omdb", "tvmaze"

    description: str | None = None
    release_date: str | None = None  # YYYY-MM-DD (or YYYY)
    year: int | None = None
    rating: float | None = None
    poster_url: str | None = None
    backdrop_url: str | None = None
    genres: list[str] = field(default_factory=list)

    imdb_id: str | None = None  # tt1234567
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    tvmaze_id: int | None = None

    runtime: int | None = None  # minutes
    status: str | None = None  # "Running", "Ended", …
    network: str | None = None
    director: str | None = None
    seasons: int | None = None
    episodes: int | None = None
    premiered: str | None = None  # YYYY-MM-DD

    language: str | None = None
    country: str | None = None
    next_episode_date: str | None = None  # YYYY-MM-DD

    raw: dict[str, Any] = field(default_factory=dict, repr=False)

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
            "description",
            "release_date",
            "year",
            "rating",
            "poster_url",
            "backdrop_url",
            "runtime",
            "status",
            "network",
            "director",
            "seasons",
            "episodes",
            "premiered",
            "imdb_id",
            "tmdb_id",
            "tvdb_id",
            "tvmaze_id",
            "language",
            "country",
            "next_episode_date",
        ):
            if getattr(self, attr) is None and getattr(other, attr) is not None:
                setattr(self, attr, getattr(other, attr))
        if not self.genres and other.genres:
            self.genres = other.genres


@dataclass
class NormalizedEpisode:
    """Platform-agnostic representation of a single episode."""

    title: str
    season_number: int
    episode_number: int
    content_type: str = "tv_show"

    description: str | None = None
    air_date: str | None = None  # YYYY-MM-DD
    runtime: int | None = None  # minutes
    rating: float | None = None

    tvmaze_id: int | None = None
    tvdb_id: int | None = None
    imdb_id: str | None = None


# ---- utility functions --------------------------------------------------- #


def _normalise_title(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    t = re.sub(r"[^\w\s]", "", t).lower().strip()
    t = re.sub(r"\s+", " ", t)
    return t


def _year_from_date(d: str | None) -> int | None:
    if not d:
        return None
    m = re.match(r"(\d{4})", d)
    return int(m.group(1)) if m else None


class ContentProvider(ABC):
    """Interface that every content platform must implement."""

    name: str = "base"

    @abstractmethod
    def discover_movies(self, page: int = 1) -> list[NormalizedContent]:
        """Return a page of movies (browse/trending).  Empty list if unsupported."""
        ...

    @abstractmethod
    def discover_tv_shows(self, page: int = 1) -> list[NormalizedContent]:
        """Return a page of TV shows (browse/trending).  Empty list if unsupported."""
        ...

    @abstractmethod
    def search(self, query: str, content_type: str | None = None) -> list[NormalizedContent]:
        """Search for content by title."""
        ...

    @abstractmethod
    def get_upcoming(self, content_type: str = "tv_show") -> list[NormalizedContent]:
        """Upcoming movies or episodes.  Empty list if unsupported."""
        ...

    def get_trending(self) -> list[NormalizedContent]:
        """Trending content.  Default implementation returns empty list."""
        return []

    def get_details(self, external_id: str) -> NormalizedContent | None:
        """Fetch full details for a single item by its provider-specific ID.
        Default returns None (not all providers support detail lookups)."""
        return None

    def get_episodes(self, external_id: str) -> list[NormalizedEpisode]:
        """Fetch all episodes for a TV show by its provider-specific ID.
        Default returns empty list."""
        return []
