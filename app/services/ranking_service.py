"""
Ranking service - orchestrates the re-ranking agent and personalized queries
"""

import logging

from sqlalchemy.orm import Session

from app.models.content import Content
from app.repositories.ranking_repo import RankingRepository

logger = logging.getLogger(__name__)


class RankingService:
    def __init__(self, db: Session):
        self.repo = RankingRepository(db)
        self.db = db

    async def run_reranking(self, user_id: int) -> int:
        """Execute the LangGraph re-ranking pipeline for a user.
        Returns the number of items ranked.
        """
        try:
            from app.agents.graph import ranking_graph

            result = await ranking_graph.run_ranking(user_id)
            return len(result)
        except Exception as e:
            logger.error(f"Re-ranking failed for user {user_id}: {e}")
            return 0

    def get_personalized_content(
        self,
        user_id: int,
        content_type: str | None = None,
        limit: int = 20,
    ) -> list[tuple[Content, float, str | None]]:
        return self.repo.get_ranked_content(user_id, content_type=content_type, limit=limit)

    def get_top_ranked(self, user_id: int, limit: int = 10):
        return self.repo.get_top_ranked(user_id, limit=limit)

    def invalidate_ranks(self, user_id: int):
        self.repo.invalidate_user_ranks(user_id)
        self.db.commit()
