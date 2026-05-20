"""
Library service — owns all Library Item mutations and their side effects.

Read queries remain on LibraryRepository directly.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import Content, LibraryItem
from app.models.library import WatchStatus
from app.models.reminder import Reminder, ReminderType
from app.repositories.library_repo import LibraryRepository
from app.repositories.ranking_repo import RankingRepository

logger = logging.getLogger(__name__)

_STATUS_MAP = {
    "watching": WatchStatus.WATCHING,
    "planned": WatchStatus.PLANNED,
    "completed": WatchStatus.COMPLETED,
    "dropped": WatchStatus.DROPPED,
    "maybe": WatchStatus.MAYBE,
}


def _resolve_status(raw: str) -> WatchStatus | None:
    return _STATUS_MAP.get(raw.lower())


class LibraryService:
    """Atomic mutations on a user's Library with ranking invalidation."""

    def __init__(self, db: Session):
        self._db = db
        self._repo = LibraryRepository(db)
        self._ranking_repo = RankingRepository(db)

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def add(
        self,
        user_id: int,
        content_id: int,
        status: str = "planned",
    ) -> LibraryItem | None:
        """Add Content to the user's Library.

        Idempotent — returns the existing item if already tracked.
        Returns None if the Content does not exist.
        """
        existing = self._repo.get_by_user_and_content(user_id, content_id)
        if existing:
            return existing

        content = self._db.query(Content).filter(Content.id == content_id).first()
        if not content:
            return None

        watch_status = _resolve_status(status) or WatchStatus.PLANNED
        item = self._repo.create(
            user_id=user_id,
            content_id=content_id,
            status=watch_status,
        )
        self._db.commit()
        return item

    def update_status(
        self,
        user_id: int,
        item_id: int,
        status: str,
        *,
        weekly_release: bool = False,
    ) -> LibraryItem | None:
        """Transition Watch Status with timestamp bookkeeping and optional Reminder.

        Returns None if the item is not found (stale-page edge case).
        """
        new_status = _resolve_status(status)
        if not new_status:
            return None

        item = self._repo.get_by_id(item_id, user_id)
        if not item:
            return None

        old_status = item.status
        item.status = new_status
        item.updated_at = datetime.now(UTC)

        if new_status == WatchStatus.WATCHING and old_status != WatchStatus.WATCHING:
            item.started_at = datetime.now(UTC)
        elif new_status == WatchStatus.COMPLETED:
            item.finished_at = datetime.now(UTC)

        if new_status == WatchStatus.WATCHING and weekly_release:
            item.weekly_release = True
            next_date = datetime.now(UTC) + timedelta(days=7)
            item.next_episode_date = next_date
            reminder = Reminder(
                user_id=user_id,
                library_item_id=item.id,
                reminder_type=ReminderType.NEXT_EPISODE,
                scheduled_time=next_date,
                message=f"New episode of {item.content.title} should be available!",
            )
            self._db.add(reminder)

        self._invalidate_rankings(user_id)
        self._db.commit()
        return item

    def update_progress(
        self,
        user_id: int,
        item_id: int,
        progress: int,
        *,
        season: int | None = None,
        episode: int | None = None,
    ) -> LibraryItem | None:
        """Update episode/page progress. Returns None if not found."""
        item = self._repo.get_by_id(item_id, user_id)
        if not item:
            return None

        item.progress = progress
        if season is not None:
            item.current_season = season
        if episode is not None:
            item.current_episode = episode
        item.updated_at = datetime.now(UTC)

        self._db.commit()
        return item

    def rate(
        self,
        user_id: int,
        item_id: int,
        rating: int,
        notes: str | None = None,
    ) -> LibraryItem | None:
        """Set rating (clamped 1–5) and optional notes. Invalidates rankings."""
        item = self._repo.get_by_id(item_id, user_id)
        if not item:
            return None

        item.rating = max(1, min(5, rating))
        if notes is not None:
            item.notes = notes
        item.updated_at = datetime.now(UTC)

        self._invalidate_rankings(user_id)
        self._db.commit()
        return item

    def delete(self, user_id: int, item_id: int) -> bool:
        """Remove a Library Item. Invalidates rankings. Returns False if not found."""
        item = self._repo.get_by_id(item_id, user_id)
        if not item:
            return False

        self._db.delete(item)
        self._invalidate_rankings(user_id)
        self._db.commit()
        return True

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _invalidate_rankings(self, user_id: int) -> None:
        self._ranking_repo.invalidate_user_ranks(user_id)
