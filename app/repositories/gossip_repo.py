"""
Gossip repository - database access for Gossip model
"""

import logging

from sqlalchemy.orm import Session

from app.models.gossip import Gossip, GossipTag

logger = logging.getLogger(__name__)


class GossipRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, gossip_id: int) -> Gossip | None:
        return (
            self.db.query(Gossip)
            .filter(
                Gossip.id == gossip_id,
                Gossip.is_active == True,
            )
            .first()
        )

    def get_feed(
        self,
        tag: str | None = None,
        limit: int = 50,
    ) -> list[Gossip]:
        query = self.db.query(Gossip).filter(Gossip.is_active == True)
        if tag:
            try:
                gossip_tag = GossipTag(tag)
                query = query.filter(Gossip.tag == gossip_tag)
            except ValueError:
                pass
        return query.order_by(Gossip.scraped_at.desc()).limit(limit).all()

    def get_featured(self) -> Gossip | None:
        return (
            self.db.query(Gossip)
            .filter(
                Gossip.is_featured == True,
                Gossip.is_active == True,
            )
            .order_by(Gossip.scraped_at.desc())
            .first()
        )

    def get_latest(self, limit: int = 6) -> list[Gossip]:
        return (
            self.db.query(Gossip)
            .filter(
                Gossip.is_active == True,
            )
            .order_by(Gossip.scraped_at.desc())
            .limit(limit)
            .all()
        )

    def get_tag_counts(self) -> dict:
        counts = {}
        for t in GossipTag:
            count = (
                self.db.query(Gossip)
                .filter(
                    Gossip.is_active == True,
                    Gossip.tag == t,
                )
                .count()
            )
            if count > 0:
                counts[t.value] = count
        return counts

    def exists_by_url(self, source_url: str) -> bool:
        return self.db.query(Gossip).filter(Gossip.source_url == source_url).first() is not None

    def create(self, **kwargs) -> Gossip:
        gossip = Gossip(**kwargs)
        self.db.add(gossip)
        self.db.flush()
        return gossip
