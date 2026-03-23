"""
Gossip service - business logic for gossip feed
"""
import logging
from typing import List, Optional
from sqlalchemy.orm import Session

from app.repositories.gossip_repo import GossipRepository
from app.models.gossip import Gossip

logger = logging.getLogger(__name__)


class GossipService:
    def __init__(self, db: Session):
        self.repo = GossipRepository(db)
        self.db = db

    def get_feed(self, tag: Optional[str] = None, limit: int = 50) -> List[Gossip]:
        return self.repo.get_feed(tag=tag, limit=limit)

    def get_featured(self) -> Optional[Gossip]:
        return self.repo.get_featured()

    def get_latest(self, limit: int = 6) -> List[Gossip]:
        return self.repo.get_latest(limit=limit)

    def get_by_id(self, gossip_id: int) -> Optional[Gossip]:
        return self.repo.get_by_id(gossip_id)

    def get_tag_counts(self) -> dict:
        return self.repo.get_tag_counts()

    async def scrape_latest(self, tracked_titles: List[str]) -> List[dict]:
        from app.agents.gossip_agent import get_gossip_agent

        agent = get_gossip_agent()
        return await agent.scrape_gossip(tracked_titles[:10])
