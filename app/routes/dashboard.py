"""
Home page route.

Replaces the old gossip-feed dashboard. Shows curated category rows from the
catalog (the full catalog itself lives behind /search), plus a personal
sidebar with library stats, upcoming reminders, and a link to the gossip feed
(moved off Home onto its own page).
"""

import logging

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.dependencies import DbDep, OptionalUserDep, login_redirect
from app.models import LibraryItem
from app.models.library import WatchStatus
from app.repositories.content_repo import ContentRepository
from app.services.reminder_service import ReminderService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["dashboard"])

GENRES = [
    "Action",
    "Comedy",
    "Sci-Fi",
    "Thriller",
    "Drama",
    "Horror",
    "Animation",
    "Documentary",
    "Romance",
    "Fantasy",
]

ROW_SIZE = 12


def _trending_or_fallback(repo: ContentRepository, content_type: str) -> list:
    """Titles most added to a library this week; falls back to top rated when
    the app has too little library activity yet to produce a real trend."""
    trending = repo.get_trending_by_library_adds(content_type=content_type, limit=ROW_SIZE)
    if trending:
        return trending
    return repo.get_top_rated(content_type=content_type, limit=ROW_SIZE)


def _pick_spotlight(new_this_week: list, top_rated: list):
    """One title to feature: the best-rated of this week's new releases, else
    just the newest release, else the catalog's top-rated title overall."""
    rated_recent = [c for c in new_this_week if c.rating]
    if rated_recent:
        return max(rated_recent, key=lambda c: c.rating)
    if new_this_week:
        return new_this_week[0]
    if top_rated:
        return top_rated[0]
    return None


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, user: OptionalUserDep, db: DbDep):
    from app.templates import templates

    if not user:
        return login_redirect(request)

    repo = ContentRepository(db)
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
    upcoming_reminders = reminder_svc.get_upcoming(user.id, limit=3)

    new_this_week = repo.get_recent(limit=ROW_SIZE)
    top_rated = repo.get_top_rated(limit=ROW_SIZE)
    sections = [
        {
            "title": "New This Week",
            "subtitle": "Just added to the catalog",
            "titles": new_this_week,
        },
        {
            "title": "Trending Movies",
            "subtitle": "What everyone is watching",
            "titles": _trending_or_fallback(repo, "movie"),
        },
        {
            "title": "Trending TV Shows",
            "subtitle": "Most tracked this week",
            "titles": _trending_or_fallback(repo, "tv_show"),
        },
        {
            "title": "Top Rated",
            "subtitle": "Highest scored in the catalog",
            "titles": top_rated,
        },
        {
            "title": "Coming Soon",
            "subtitle": "Releasing in the next few months",
            "titles": repo.get_coming_soon(limit=ROW_SIZE),
        },
    ]
    sections = [s for s in sections if s["titles"]]

    spotlight = _pick_spotlight(new_this_week, top_rated)

    all_shown_ids = {c.id for s in sections for c in s["titles"]}
    if spotlight:
        all_shown_ids.add(spotlight.id)
    library_items_map = {
        item.content_id: item
        for item in db.query(LibraryItem)
        .filter(LibraryItem.user_id == user.id, LibraryItem.content_id.in_(all_shown_ids))
        .all()
    }

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "library_stats": library_stats,
            "upcoming_reminders": upcoming_reminders,
            "sections": sections,
            "spotlight": spotlight,
            "genres": GENRES,
            "library_items_map": library_items_map,
        },
    )
