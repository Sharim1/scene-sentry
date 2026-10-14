"""
Episode repository - database access for the Episode model.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.episode import Episode
from app.services.providers.base import NormalizedEpisode

logger = logging.getLogger(__name__)


class EpisodeRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_content(self, content_id: int) -> list[Episode]:
        return (
            self.db.query(Episode)
            .filter(Episode.content_id == content_id)
            .order_by(Episode.season_number, Episode.episode_number)
            .all()
        )

    def count_by_content(self, content_id: int) -> int:
        return self.db.query(Episode).filter(Episode.content_id == content_id).count()

    def get_season_count(self, content_id: int) -> int:
        from sqlalchemy import func

        row = self.db.query(func.max(Episode.season_number)).filter(Episode.content_id == content_id).scalar()
        return row or 0

    def upsert_episode(
        self,
        content_id: int,
        ne: NormalizedEpisode,
    ) -> Episode:
        existing = (
            self.db.query(Episode)
            .filter_by(
                content_id=content_id,
                season_number=ne.season_number,
                episode_number=ne.episode_number,
            )
            .first()
        )

        if existing:
            if ne.title and not existing.title:
                existing.title = ne.title[:300]
            if ne.description and not existing.description:
                existing.description = ne.description
            if ne.air_date and not existing.air_date:
                existing.air_date = ne.air_date
            if ne.runtime and not existing.runtime:
                existing.runtime = ne.runtime
            if ne.rating and not existing.rating:
                existing.rating = ne.rating
            if ne.tvmaze_id and not existing.tvmaze_id:
                existing.tvmaze_id = ne.tvmaze_id
            if ne.tvdb_id and not existing.tvdb_id:
                existing.tvdb_id = ne.tvdb_id
            if ne.imdb_id and not existing.imdb_id:
                existing.imdb_id = ne.imdb_id
            existing.updated_at = datetime.now(UTC)
            return existing

        ep = Episode(
            content_id=content_id,
            season_number=ne.season_number,
            episode_number=ne.episode_number,
            title=(ne.title or "")[:300] or None,
            description=ne.description,
            air_date=ne.air_date,
            runtime=ne.runtime,
            rating=ne.rating,
            tvmaze_id=ne.tvmaze_id,
            tvdb_id=ne.tvdb_id,
            imdb_id=ne.imdb_id,
        )
        self.db.add(ep)
        self.db.flush()
        return ep

    def bulk_upsert(
        self,
        content_id: int,
        episodes: list[NormalizedEpisode],
    ) -> int:
        """Save a show's episodes in a few statements, whatever their number.

        Same rules as ``upsert_episode``: new episodes are inserted, blanks on existing ones are
        filled, nothing already set is overwritten. Returns how many distinct episodes were given.
        """
        merged = _merge_duplicates(episodes)
        if not merged:
            return 0

        now = datetime.now(UTC)
        rows = [_episode_row(content_id, ne, now) for ne in merged.values()]
        insert = _dialect_insert(self.db)
        for i in range(0, len(rows), _EPISODE_CHUNK):
            stmt = insert(Episode.__table__).values(rows[i : i + _EPISODE_CHUNK])
            incoming = stmt.excluded
            stmt = stmt.on_conflict_do_update(
                index_elements=["content_id", "season_number", "episode_number"],
                set_={
                    **{col: func.coalesce(getattr(Episode, col), getattr(incoming, col)) for col in _FILL_BLANK},
                    "updated_at": now,
                },
            )
            self.db.execute(stmt)
        return len(merged)


_EPISODE_CHUNK = 500
_FILL_BLANK = ("title", "description", "air_date", "runtime", "rating", "tvmaze_id", "tvdb_id", "imdb_id")


def _dialect_insert(db: Session) -> Callable[..., Any]:
    """The ``INSERT ... ON CONFLICT`` builder for the database in use (Postgres live, SQLite in tests)."""
    if db.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        return pg_insert
    from sqlalchemy.dialects.sqlite import insert as sqlite_insert

    return sqlite_insert


def _merge_duplicates(episodes: list[NormalizedEpisode]) -> dict[tuple[int, int], NormalizedEpisode]:
    """One entry per (season, episode); a later duplicate only fills what the earlier one left blank."""
    merged: dict[tuple[int, int], NormalizedEpisode] = {}
    for ne in episodes:
        key = (ne.season_number, ne.episode_number)
        first = merged.get(key)
        if first is None:
            merged[key] = ne
            continue
        for field in ("title", "description", "air_date", "runtime", "rating", "tvmaze_id", "tvdb_id", "imdb_id"):
            if not getattr(first, field) and getattr(ne, field):
                setattr(first, field, getattr(ne, field))
    return merged


def _episode_row(content_id: int, ne: NormalizedEpisode, now: datetime) -> dict:
    return {
        "content_id": content_id,
        "season_number": ne.season_number,
        "episode_number": ne.episode_number,
        "title": (ne.title or "")[:300] or None,
        "description": ne.description or None,
        "air_date": ne.air_date or None,
        "runtime": ne.runtime or None,
        "rating": ne.rating or None,
        "tvmaze_id": ne.tvmaze_id or None,
        "tvdb_id": ne.tvdb_id or None,
        "imdb_id": ne.imdb_id or None,
        "created_at": now,
        "updated_at": now,
    }
