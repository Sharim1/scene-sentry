"""
Reminder service - business logic for reminders
"""
import logging
from typing import List, Optional, Dict
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.repositories.reminder_repo import ReminderRepository
from app.models.reminder import Reminder

logger = logging.getLogger(__name__)


class ReminderService:
    def __init__(self, db: Session):
        self.repo = ReminderRepository(db)
        self.db = db

    def get_upcoming(self, user_id: int, limit: int = 5) -> List[Reminder]:
        return self.repo.get_upcoming(user_id, limit=limit)

    def get_by_month(self, user_id: int, year: int, month: int) -> List[Reminder]:
        return self.repo.get_by_month(user_id, year, month)

    def get_calendar_dots(self, user_id: int, year: int, month: int) -> Dict[int, int]:
        return self.repo.get_calendar_dots(user_id, year, month)

    def create_reminder(self, user_id: int, **kwargs) -> Reminder:
        reminder = self.repo.create(user_id=user_id, **kwargs)
        self.db.commit()
        return reminder

    def toggle_reminder(self, reminder_id: int, user_id: int) -> Optional[Reminder]:
        reminder = self.repo.toggle(reminder_id, user_id)
        if reminder:
            self.db.commit()
        return reminder

    def delete_reminder(self, reminder_id: int, user_id: int) -> bool:
        deleted = self.repo.delete(reminder_id, user_id)
        if deleted:
            self.db.commit()
        return deleted

    def get_grouped_by_date(
        self, user_id: int, year: int, month: int, tz_name: str = "UTC"
    ) -> Dict[str, List[Reminder]]:
        from app.utils.timezone import utc_to_local

        reminders = self.repo.get_by_month(user_id, year, month)
        grouped: Dict[str, List[Reminder]] = {}
        for r in reminders:
            local_dt = utc_to_local(r.scheduled_time, tz_name)
            key = local_dt.strftime("%A, %b %d").upper()
            grouped.setdefault(key, []).append(r)
        return grouped

    def process_due_reminders(self) -> int:
        """Find due reminders, create in-app notifications, send emails, mark sent."""
        from app.services.notification_service import NotificationService
        from app.services.email_service import send_reminder_email
        from app.utils.timezone import utc_to_local

        due = self.repo.get_due()
        if not due:
            return 0

        notif_svc = NotificationService(self.db)

        for reminder in due:
            try:
                notif_svc.create_from_reminder(reminder)
            except Exception as exc:
                logger.error("Failed to create notification for reminder %s: %s", reminder.id, exc)

            user = reminder.user
            if user and user.email and user.email_notifications:
                try:
                    tz = user.timezone or "UTC"
                    local_dt = utc_to_local(reminder.scheduled_time, tz)
                    time_str = local_dt.strftime("%b %d, %Y at %I:%M %p %Z")

                    content_title = (
                        reminder.content.title if reminder.content else "Untitled"
                    )
                    rtype = reminder.reminder_type.value.replace("_", " ").title()

                    send_reminder_email(
                        to_email=user.email,
                        subject=f"Reminder: {content_title}",
                        content_title=content_title,
                        reminder_message=reminder.message or f"{rtype} reminder for {content_title}",
                        reminder_type=rtype,
                        scheduled_time_display=time_str,
                    )
                except Exception as exc:
                    logger.error("Failed to email reminder %s: %s", reminder.id, exc)

            self.repo.mark_sent(reminder.id)

        self.db.commit()
        return len(due)
