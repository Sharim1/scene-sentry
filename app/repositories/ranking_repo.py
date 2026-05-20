"""
Ranking repository - database access for UserContentRank model
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models.content import Content
from app.models.ranking import UserContentRank

logger = logging.getLogger(__name__)


class RankingRepository:
    def __init__(self, db: Session):
        self.db = db

    def upsert_rank(
        self,
        user_id: int,
        content_id: int,
        score: float,
        reasoning: str | None = None,
    ) -> UserContentRank:
        existing = (
            self.db.query(UserContentRank)
            .filter(
                UserContentRank.user_id == user_id,
                UserContentRank.content_id == content_id,
            )
            .first()
        )

        if existing:
            existing.rank_score = score
            existing.reasoning = reasoning
            existing.ranked_at = datetime.now(UTC)
            self.db.flush()
            return existing

        rank = UserContentRank(
            user_id=user_id,
            content_id=content_id,
            rank_score=score,
            reasoning=reasoning,
        )
        self.db.add(rank)
        self.db.flush()
        return rank

    def get_ranked_content(
        self,
        user_id: int,
        content_type: str | None = None,
        limit: int = 20,
    ) -> list[tuple[Content, float, str | None]]:
        """Return content ordered by rank_score DESC, with score and reasoning."""
        query = self.db.query(Content, UserContentRank.rank_score, UserContentRank.reasoning).outerjoin(
            UserContentRank,
            (UserContentRank.content_id == Content.id) & (UserContentRank.user_id == user_id),
        )
        if content_type:
            query = query.filter(Content.content_type == content_type)

        query = query.order_by(
            UserContentRank.rank_score.desc().nullslast(),
            Content.rating.desc().nullslast(),
        )
        return query.limit(limit).all()

    def get_stale_ranks(self, user_id: int, max_age_hours: int = 24) -> list[UserContentRank]:
        cutoff = datetime.now(UTC) - timedelta(hours=max_age_hours)
        return (
            self.db.query(UserContentRank)
            .filter(
                UserContentRank.user_id == user_id,
                UserContentRank.ranked_at < cutoff,
            )
            .all()
        )

    def get_unranked_content(
        self,
        user_id: int,
        content_type: str | None = None,
        limit: int = 50,
    ) -> list[Content]:
        ranked_ids = (
            self.db.query(UserContentRank.content_id)
            .filter(
                UserContentRank.user_id == user_id,
            )
            .subquery()
        )

        query = self.db.query(Content).filter(~Content.id.in_(ranked_ids))
        if content_type:
            query = query.filter(Content.content_type == content_type)
        return query.order_by(Content.rating.desc().nullslast()).limit(limit).all()

    def invalidate_user_ranks(self, user_id: int):
        """Mark all ranks as stale by setting ranked_at far in the past."""
        self.db.query(UserContentRank).filter(
            UserContentRank.user_id == user_id,
        ).update(
            {"ranked_at": datetime(2000, 1, 1, tzinfo=UTC)},
            synchronize_session="fetch",
        )
        self.db.flush()

    def get_top_ranked(self, user_id: int, limit: int = 10) -> list[tuple[Content, float, str | None]]:
        return (
            self.db.query(Content, UserContentRank.rank_score, UserContentRank.reasoning)
            .join(UserContentRank, UserContentRank.content_id == Content.id)
            .filter(UserContentRank.user_id == user_id)
            .order_by(UserContentRank.rank_score.desc())
            .limit(limit)
            .all()
        )
