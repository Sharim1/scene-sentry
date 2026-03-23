"""
Library repository - database access for LibraryItem model
"""
import logging
from typing import List, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.library import LibraryItem, WatchStatus

logger = logging.getLogger(__name__)


class LibraryRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, item_id: int, user_id: int) -> Optional[LibraryItem]:
        return self.db.query(LibraryItem).filter(
            LibraryItem.id == item_id,
            LibraryItem.user_id == user_id,
        ).first()

    def get_by_user(
        self,
        user_id: int,
        status: Optional[WatchStatus] = None,
        limit: int = 100,
    ) -> List[LibraryItem]:
        query = self.db.query(LibraryItem).filter(LibraryItem.user_id == user_id)
        if status:
            query = query.filter(LibraryItem.status == status)
        return query.order_by(LibraryItem.updated_at.desc()).limit(limit).all()

    def get_by_user_and_content(self, user_id: int, content_id: int) -> Optional[LibraryItem]:
        return self.db.query(LibraryItem).filter(
            LibraryItem.user_id == user_id,
            LibraryItem.content_id == content_id,
        ).first()

    def count_by_status(self, user_id: int) -> dict:
        counts = {}
        for s in WatchStatus:
            count = self.db.query(LibraryItem).filter(
                LibraryItem.user_id == user_id,
                LibraryItem.status == s,
            ).count()
            counts[s.value] = count
        return counts

    def get_tracked_titles(self, user_id: int) -> List[str]:
        items = self.db.query(LibraryItem).filter(
            LibraryItem.user_id == user_id,
            LibraryItem.status.in_([WatchStatus.WATCHING, WatchStatus.PLANNED]),
        ).all()
        return [item.content.title for item in items if item.content]

    def get_all_tracked_titles(self) -> List[str]:
        items = self.db.query(LibraryItem).filter(
            LibraryItem.status.in_([WatchStatus.WATCHING, WatchStatus.PLANNED]),
        ).all()
        titles = set()
        for item in items:
            if item.content:
                titles.add(item.content.title)
        return list(titles)

    def create(self, **kwargs) -> LibraryItem:
        item = LibraryItem(**kwargs)
        self.db.add(item)
        self.db.flush()
        return item

    def update_status(self, item_id: int, user_id: int, status: WatchStatus) -> Optional[LibraryItem]:
        item = self.get_by_id(item_id, user_id)
        if item:
            item.status = status
            item.updated_at = datetime.now(timezone.utc)
            self.db.flush()
        return item

    def update_rating(self, item_id: int, user_id: int, rating: int, notes: Optional[str] = None) -> Optional[LibraryItem]:
        item = self.get_by_id(item_id, user_id)
        if item:
            item.rating = min(5, max(1, rating))
            if notes is not None:
                item.notes = notes
            item.updated_at = datetime.now(timezone.utc)
            self.db.flush()
        return item
