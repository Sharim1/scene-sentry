"""
Notification service - business logic for in-app notifications and email delivery
"""
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.repositories.notification_repo import NotificationRepository
from app.models.notification import Notification
from app.models.reminder import Reminder

logger = logging.getLogger(__name__)


class NotificationService:
    def __init__(self, db: Session):
        self.repo = NotificationRepository(db)
        self.db = db

    def create_from_reminder(self, reminder: Reminder) -> Notification:
        """Build an in-app notification from a due reminder."""
        content_title = (
            reminder.content.title if reminder.content else "Untitled"
        )
        rtype = reminder.reminder_type.value.replace("_", " ").title()

        title = f"{rtype} Reminder"
        body = reminder.message or f"{rtype} reminder for {content_title}"
        link = f"/{reminder.content_id}" if reminder.content_id else "/reminders"

        notification = self.repo.create(
            user_id=reminder.user_id,
            reminder_id=reminder.id,
            title=title,
            body=body,
            link=link,
        )
        return notification

    def get_for_user(
        self, user_id: int, unread_only: bool = False, limit: int = 30
    ) -> List[Notification]:
        return self.repo.get_by_user(user_id, unread_only=unread_only, limit=limit)

    def count_unread(self, user_id: int) -> int:
        return self.repo.count_unread(user_id)

    def mark_read(self, notification_id: int, user_id: int) -> Optional[Notification]:
        n = self.repo.mark_read(notification_id, user_id)
        if n:
            self.db.commit()
        return n

    def mark_all_read(self, user_id: int) -> int:
        count = self.repo.mark_all_read(user_id)
        self.db.commit()
        return count

    def has_unread_since(self, user_id: int, since: datetime) -> bool:
        return self.repo.has_unread_since(user_id, since)

    def to_dict(self, n: Notification) -> Dict[str, Any]:
        return {
            "id": n.id,
            "title": n.title,
            "body": n.body,
            "link": n.link,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
