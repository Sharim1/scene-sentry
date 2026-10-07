"""
Library routes for tracking content
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.dependencies import DbDep, OptionalUserDep, login_redirect
from app.models import Content, LibraryItem
from app.models.library import WatchStatus
from app.repositories.library_repo import LibraryRepository
from app.services.library_service import LibraryService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/library", tags=["library"])


@router.get("", response_class=HTMLResponse)
def library(
    request: Request,
    user: OptionalUserDep,
    db: DbDep,
    type: Annotated[str, Query(alias="type")] = "all",
    status: Annotated[str, Query()] = "all",
    q: Annotated[str | None, Query()] = None,
):
    """Library page with filtering and search"""
    from app.templates import templates

    if not user:
        return login_redirect(request)

    query = db.query(LibraryItem).filter(LibraryItem.user_id == user.id)
    query = query.join(Content)

    search_query = q
    if q:
        query = query.filter(Content.title.ilike(f"%{q}%") | Content.description.ilike(f"%{q}%"))

    if type != "all":
        query = query.filter(Content.content_type == type)

    if status != "all":
        status_map = {
            "watching": WatchStatus.WATCHING,
            "planned": WatchStatus.PLANNED,
            "completed": WatchStatus.COMPLETED,
            "dropped": WatchStatus.DROPPED,
            "maybe": WatchStatus.MAYBE,
        }
        if status in status_map:
            query = query.filter(LibraryItem.status == status_map[status])

    library_items = query.order_by(LibraryItem.updated_at.desc()).all()

    repo = LibraryRepository(db)
    counts = repo.count_by_status(user.id)
    counts["all"] = db.query(LibraryItem).filter(LibraryItem.user_id == user.id).count()

    return templates.TemplateResponse(
        "library.html",
        {
            "request": request,
            "user": user,
            "library_items": library_items,
            "current_type": type,
            "current_status": status,
            "search_query": search_query,
            "counts": counts,
        },
    )


@router.post("/item/{item_id}/update")
def update_library_item(
    request: Request,
    item_id: int,
    user: OptionalUserDep,
    db: DbDep,
    status: Annotated[str, Form()],
    weekly_release: Annotated[bool, Form()] = False,
):
    """Update library item status"""
    if not user:
        return login_redirect(request)

    svc = LibraryService(db)
    svc.update_status(user.id, item_id, status, weekly_release=weekly_release)

    return RedirectResponse(url="/library", status_code=303)


@router.post("/item/{item_id}/progress")
def update_progress(
    request: Request,
    item_id: int,
    user: OptionalUserDep,
    db: DbDep,
    progress: Annotated[int, Form()],
    season: Annotated[int | None, Form()] = None,
    episode: Annotated[int | None, Form()] = None,
):
    """Update progress on a library item"""
    if not user:
        return login_redirect(request)

    svc = LibraryService(db)
    svc.update_progress(user.id, item_id, progress, season=season, episode=episode)

    return RedirectResponse(url="/library", status_code=303)


@router.post("/item/{item_id}/rate")
def rate_item(
    request: Request,
    item_id: int,
    user: OptionalUserDep,
    db: DbDep,
    rating: Annotated[int, Form()],
    notes: Annotated[str | None, Form()] = None,
):
    """Rate a library item"""
    if not user:
        return login_redirect(request)

    svc = LibraryService(db)
    svc.rate(user.id, item_id, rating, notes=notes)

    return RedirectResponse(url="/library", status_code=303)


@router.post("/item/{item_id}/delete")
def delete_library_item(
    request: Request,
    item_id: int,
    user: OptionalUserDep,
    db: DbDep,
):
    """Remove item from library"""
    if not user:
        return login_redirect(request)

    svc = LibraryService(db)
    svc.delete(user.id, item_id)

    return RedirectResponse(url="/library", status_code=303)


@router.post("/add")
def add_to_library(
    request: Request,
    user: OptionalUserDep,
    db: DbDep,
    content_id: Annotated[int, Form()],
    status: Annotated[str, Form()] = "planned",
):
    """Add content to library"""
    if not user:
        return login_redirect(request)

    svc = LibraryService(db)
    svc.add(user.id, content_id, status)

    return RedirectResponse(url="/library", status_code=303)
