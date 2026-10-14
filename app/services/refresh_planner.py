"""Refresh planner (ADR-0006): which titles are due for refresh, in what order.

Tiers, most urgent first: hot (tracked by a user, or airing within the window), warm
(running shows, announced movies), cold (ended / released), failed (repeated failures,
exponential backoff). Within a tier, never-refreshed titles go first.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, exists, func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.content import Content
from app.models.episode import Episode
from app.models.library import LibraryItem

HOT, WARM, COLD, FAILED = 0, 1, 2, 3
_ENDED = ("ended", "canceled", "cancelled")


def _naive(dt: datetime) -> datetime:
    return dt.astimezone(UTC).replace(tzinfo=None)


def tier_rank(now: datetime):
    """SQL expression giving each content row its tier rank at ``now``."""
    window_end = now + timedelta(days=settings.refresh_airing_window_days)
    today, soon = now.date().isoformat(), window_end.date().isoformat()
    tracked = exists().where(LibraryItem.content_id == Content.id)
    airing = exists().where(and_(Episode.content_id == Content.id, Episode.air_date >= today, Episode.air_date <= soon))
    next_ep_soon = and_(Content.next_episode_date >= _naive(now), Content.next_episode_date <= _naive(window_end))
    running = and_(
        Content.content_type == "tv_show",
        or_(Content.status.is_(None), func.lower(Content.status).notin_(_ENDED)),
    )
    announced = and_(Content.content_type == "movie", Content.release_date > today)
    return case(
        (Content.refresh_attempts >= settings.refresh_failure_threshold, FAILED),
        (or_(tracked, airing, next_ep_soon), HOT),
        (or_(running, announced), WARM),
        else_=COLD,
    )


def due_titles(db: Session, limit: int, now: datetime, content_type: str | None = None) -> list[Content]:
    """Titles whose refresh is due at ``now``, most urgent first."""
    q = db.query(Content).filter(or_(Content.next_refresh_at.is_(None), Content.next_refresh_at <= now))
    if content_type:
        q = q.filter(Content.content_type == content_type)
    return (
        q.order_by(
            tier_rank(now),
            case((Content.last_refreshed_at.is_(None), 0), else_=1),
            Content.next_refresh_at,
            Content.id,
        )
        .limit(limit)
        .all()
    )


def success_delay(db: Session, content_id: int, now: datetime) -> timedelta:
    rank = db.query(tier_rank(now)).filter(Content.id == content_id).scalar()
    if rank == HOT:
        return timedelta(hours=settings.refresh_hot_hours)
    if rank == WARM:
        return timedelta(hours=settings.refresh_warm_hours)
    return timedelta(days=min(settings.refresh_cold_days, settings.refresh_cold_days_max))


def failure_delay(attempts: int) -> timedelta:
    """Exponential backoff from the base delay, capped."""
    cap = timedelta(days=settings.refresh_failure_backoff_cap_days)
    base = timedelta(hours=settings.refresh_failure_backoff_base_hours)
    return min(base * 2 ** max(attempts - 1, 0), cap)


def failing_titles(db: Session, min_failures: int | None = None) -> list[Content]:
    """Report: titles that keep failing, worst first."""
    threshold = min_failures or settings.refresh_failure_threshold
    return (
        db.query(Content)
        .filter(Content.refresh_attempts >= threshold)
        .order_by(Content.refresh_attempts.desc(), Content.id)
        .all()
    )
