"""
Episode repository - database access for the Episode model.
"""

import logging
from datetime import UTC, datetime

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
        count = 0
        for ne in episodes:
            try:
                self.upsert_episode(content_id, ne)
                count += 1
            except Exception as e:
                logger.warning(
                    "Failed to upsert episode S%02dE%02d: %s",
                    ne.season_number,
                    ne.episode_number,
                    e,
                )
        return count
