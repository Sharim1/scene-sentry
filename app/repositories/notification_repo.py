"""
Notification repository - database access for Notification model
"""

import logging
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.models.notification import Notification

logger = logging.getLogger(__name__)


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, **kwargs) -> Notification:
        notification = Notification(**kwargs)
        self.db.add(notification)
        self.db.flush()
        return notification

    def get_by_user(self, user_id: int, unread_only: bool = False, limit: int = 30) -> list[Notification]:
        q = self.db.query(Notification).filter(Notification.user_id == user_id)
        if unread_only:
            q = q.filter(Notification.is_read == False)
        return q.order_by(Notification.created_at.desc()).limit(limit).all()

    def count_unread(self, user_id: int) -> int:
        return (
            self.db.query(Notification).filter(Notification.user_id == user_id, Notification.is_read == False).count()
        )

    def mark_read(self, notification_id: int, user_id: int) -> Notification | None:
        n = (
            self.db.query(Notification)
            .filter(Notification.id == notification_id, Notification.user_id == user_id)
            .first()
        )
        if n and not n.is_read:
            n.is_read = True
            n.read_at = datetime.now(UTC)
            self.db.flush()
        return n

    def mark_all_read(self, user_id: int) -> int:
        now = datetime.now(UTC)
        count = (
            self.db.query(Notification)
            .filter(Notification.user_id == user_id, Notification.is_read == False)
            .update({"is_read": True, "read_at": now})
        )
        self.db.flush()
        return count

    def has_unread_since(self, user_id: int, since: datetime) -> bool:
        return (
            self.db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.is_read == False,
                Notification.created_at > since,
            )
            .first()
            is not None
        )

    def delete_old(self, days: int = 30) -> int:
        from datetime import timedelta

        cutoff = datetime.now(UTC) - timedelta(days=days)
        count = (
            self.db.query(Notification).filter(Notification.is_read == True, Notification.created_at < cutoff).delete()
        )
        self.db.flush()
        return count
