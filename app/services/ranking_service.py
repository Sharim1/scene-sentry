"""
Ranking service — orchestrates the LangGraph re-ranking agent.

Read queries (get_ranked_content, get_top_ranked) belong on
RankingRepository directly; this service exists only for operations
that coordinate the agent or have transactional side effects.
"""

import logging

from sqlalchemy.orm import Session

from app.repositories.ranking_repo import RankingRepository

logger = logging.getLogger(__name__)


class RankingService:
    """Orchestrates ranking mutations: running the agent and invalidating stale scores."""

    def __init__(self, db: Session):
        self._repo = RankingRepository(db)
        self._db = db

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

    def invalidate_ranks(self, user_id: int):
        self._repo.invalidate_user_ranks(user_id)
        self._db.commit()
