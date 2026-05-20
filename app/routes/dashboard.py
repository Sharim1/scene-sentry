"""
Dashboard routes
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func

from app.dependencies import DbDep, OptionalUserDep
from app.models import Content, LibraryItem
from app.models.library import WatchStatus
from app.services.gossip_service import GossipService
from app.services.reminder_service import ReminderService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])


def get_ai_agent_status():
    from app.config import settings

    if not settings.tavily_api_key:
        return {
            "status": "inactive",
            "message": "Tavily API key not configured",
            "details": "Add TAVILY_API_KEY to .env to enable gossip scraping",
            "color": "yellow",
        }
    if not settings.gemini_api_key:
        return {
            "status": "limited",
            "message": "Gossip scraping enabled",
            "details": "Add GEMINI_API_KEY for AI-powered re-ranking",
            "color": "blue",
        }
    return {
        "status": "active",
        "message": "AI agents fully operational",
        "details": "Content re-ranking & gossip scraping active",
        "color": "green",
    }


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: OptionalUserDep, db: DbDep):
    from app.templates import templates

    if not user:
        return RedirectResponse(url="/login", status_code=303)

    gossip_svc = GossipService(db)
    reminder_svc = ReminderService(db)

    library_stats = {
        "watching": db.query(LibraryItem)
        .filter(LibraryItem.user_id == user.id, LibraryItem.status == WatchStatus.WATCHING)
        .count(),
        "planned": db.query(LibraryItem)
        .filter(LibraryItem.user_id == user.id, LibraryItem.status == WatchStatus.PLANNED)
        .count(),
        "completed": db.query(LibraryItem)
        .filter(LibraryItem.user_id == user.id, LibraryItem.status == WatchStatus.COMPLETED)
        .count(),
        "maybe": db.query(LibraryItem)
        .filter(LibraryItem.user_id == user.id, LibraryItem.status == WatchStatus.MAYBE)
        .count(),
    }

    upcoming_reminders = reminder_svc.get_upcoming(user.id, limit=5)
    latest_gossip = gossip_svc.get_latest(limit=6)
    featured_gossip = gossip_svc.get_featured()

    trending = (
        db.query(Content)
        .join(LibraryItem)
        .filter(LibraryItem.added_at >= datetime.now(UTC) - timedelta(days=7))
        .group_by(Content.id)
        .order_by(func.count(LibraryItem.id).desc())
        .limit(5)
        .all()
    )

    ai_status = get_ai_agent_status()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "library_stats": library_stats,
            "upcoming_reminders": upcoming_reminders,
            "latest_gossip": latest_gossip,
            "featured_gossip": featured_gossip,
            "trending": trending,
            "ai_status": ai_status,
        },
    )
