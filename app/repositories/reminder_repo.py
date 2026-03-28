"""
Reminder repository - database access for Reminder model
"""
import logging
from typing import List, Optional, Dict, Tuple
from datetime import datetime, timezone
from sqlalchemy.orm import Session

from app.models.reminder import Reminder

logger = logging.getLogger(__name__)


class ReminderRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_id(self, reminder_id: int, user_id: int) -> Optional[Reminder]:
        return self.db.query(Reminder).filter(
            Reminder.id == reminder_id,
            Reminder.user_id == user_id,
        ).first()

    def get_by_user(self, user_id: int, limit: int = 100) -> List[Reminder]:
        return self.db.query(Reminder).filter(
            Reminder.user_id == user_id,
        ).order_by(Reminder.scheduled_time.asc()).limit(limit).all()

    def get_by_month(self, user_id: int, year: int, month: int) -> List[Reminder]:
        from calendar import monthrange
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        _, last_day = monthrange(year, month)
        end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)
        return self.db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.scheduled_time >= start,
            Reminder.scheduled_time <= end,
        ).order_by(Reminder.scheduled_time.asc()).all()

    def get_upcoming_paged(
        self, user_id: int, offset: int = 0, limit: int = 10,
    ) -> Tuple[List[Reminder], int]:
        """Return upcoming (future, unsent) reminders with total count for pagination."""
        now = datetime.now(timezone.utc)
        base = self.db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.scheduled_time >= now,
        )
        total = base.count()
        items = (
            base.order_by(Reminder.scheduled_time.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return items, total

    def get_upcoming(self, user_id: int, limit: int = 5) -> List[Reminder]:
        now = datetime.now(timezone.utc)
        return self.db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.scheduled_time >= now,
            Reminder.sent == False,
        ).order_by(Reminder.scheduled_time.asc()).limit(limit).all()

    def get_due(self) -> List[Reminder]:
        now = datetime.now(timezone.utc)
        return self.db.query(Reminder).filter(
            Reminder.scheduled_time <= now,
            Reminder.sent == False,
            Reminder.is_enabled == True,
        ).all()

    def get_calendar_dots(
        self, user_id: int, year: int, month: int, tz_name: str = "UTC",
    ) -> Dict[int, int]:
        """Return {day_number: count} for upcoming reminders in the given month.

        Only includes reminders whose scheduled_time >= now so dots
        match what appears in the upcoming-only feed.
        """
        from app.utils.timezone import utc_to_local
        from calendar import monthrange

        now = datetime.now(timezone.utc)
        start = datetime(year, month, 1, tzinfo=timezone.utc)
        _, last_day = monthrange(year, month)
        end = datetime(year, month, last_day, 23, 59, 59, tzinfo=timezone.utc)

        floor = max(start, now)
        if floor > end:
            return {}

        reminders = self.db.query(Reminder).filter(
            Reminder.user_id == user_id,
            Reminder.scheduled_time >= floor,
            Reminder.scheduled_time <= end,
        ).all()

        dots: Dict[int, int] = {}
        for r in reminders:
            local_dt = utc_to_local(r.scheduled_time, tz_name)
            day = local_dt.day
            dots[day] = dots.get(day, 0) + 1
        return dots

    def create(self, **kwargs) -> Reminder:
        reminder = Reminder(**kwargs)
        self.db.add(reminder)
        self.db.flush()
        return reminder

    def toggle(self, reminder_id: int, user_id: int) -> Optional[Reminder]:
        reminder = self.get_by_id(reminder_id, user_id)
        if reminder:
            reminder.is_enabled = not reminder.is_enabled
            self.db.flush()
        return reminder

    def delete(self, reminder_id: int, user_id: int) -> bool:
        reminder = self.get_by_id(reminder_id, user_id)
        if reminder:
            self.db.delete(reminder)
            self.db.flush()
            return True
        return False

    def mark_sent(self, reminder_id: int):
        reminder = self.db.query(Reminder).filter(Reminder.id == reminder_id).first()
        if reminder:
            reminder.sent = True
            reminder.sent_at = datetime.now(timezone.utc)
            self.db.flush()
