"""
Library routes for tracking content
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from app.dependencies import DbDep, OptionalUserDep
from app.models import LibraryItem, Content, Reminder
from app.models.library import WatchStatus
from app.models.reminder import ReminderType

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
        return RedirectResponse(url="/login", status_code=303)

    query = db.query(LibraryItem).filter(LibraryItem.user_id == user.id)

    query = query.join(Content)

    search_query = q
    if q:
        query = query.filter(
            Content.title.ilike(f"%{q}%") | Content.description.ilike(f"%{q}%")
        )

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

    counts = {
        "all": db.query(LibraryItem).filter(LibraryItem.user_id == user.id).count(),
        "watching": db.query(LibraryItem)
        .filter(
            LibraryItem.user_id == user.id,
            LibraryItem.status == WatchStatus.WATCHING,
        )
        .count(),
        "planned": db.query(LibraryItem)
        .filter(
            LibraryItem.user_id == user.id,
            LibraryItem.status == WatchStatus.PLANNED,
        )
        .count(),
        "completed": db.query(LibraryItem)
        .filter(
            LibraryItem.user_id == user.id,
            LibraryItem.status == WatchStatus.COMPLETED,
        )
        .count(),
        "dropped": db.query(LibraryItem)
        .filter(
            LibraryItem.user_id == user.id,
            LibraryItem.status == WatchStatus.DROPPED,
        )
        .count(),
    }

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
        return RedirectResponse(url="/login", status_code=303)

    library_item = db.query(LibraryItem).filter(
        LibraryItem.id == item_id,
        LibraryItem.user_id == user.id,
    ).first()

    if library_item:
        status_map = {
            "watching": WatchStatus.WATCHING,
            "planned": WatchStatus.PLANNED,
            "completed": WatchStatus.COMPLETED,
            "dropped": WatchStatus.DROPPED,
            "maybe": WatchStatus.MAYBE,
        }

        new_status = status_map.get(status)
        if new_status:
            old_status = library_item.status
            library_item.status = new_status
            library_item.updated_at = datetime.now(timezone.utc)

            if new_status == WatchStatus.WATCHING and old_status != WatchStatus.WATCHING:
                library_item.started_at = datetime.now(timezone.utc)
            elif new_status == WatchStatus.COMPLETED:
                library_item.finished_at = datetime.now(timezone.utc)

            if new_status == WatchStatus.WATCHING and weekly_release:
                library_item.weekly_release = True
                next_date = datetime.now(timezone.utc) + timedelta(days=7)
                library_item.next_episode_date = next_date

                reminder = Reminder(
                    user_id=user.id,
                    library_item_id=library_item.id,
                    reminder_type=ReminderType.NEXT_EPISODE,
                    scheduled_time=next_date,
                    message=f"New episode of {library_item.content.title} should be available!",
                )
                db.add(reminder)

            db.commit()

            from app.services.ranking_service import RankingService

            RankingService(db).invalidate_ranks(user.id)

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
        return RedirectResponse(url="/login", status_code=303)

    library_item = db.query(LibraryItem).filter(
        LibraryItem.id == item_id,
        LibraryItem.user_id == user.id,
    ).first()

    if library_item:
        library_item.progress = progress
        if season is not None:
            library_item.current_season = season
        if episode is not None:
            library_item.current_episode = episode
        library_item.updated_at = datetime.now(timezone.utc)
        db.commit()

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
        return RedirectResponse(url="/login", status_code=303)

    library_item = db.query(LibraryItem).filter(
        LibraryItem.id == item_id,
        LibraryItem.user_id == user.id,
    ).first()

    if library_item:
        library_item.rating = min(5, max(1, rating))
        if notes:
            library_item.notes = notes
        library_item.updated_at = datetime.now(timezone.utc)
        db.commit()

        from app.services.ranking_service import RankingService

        RankingService(db).invalidate_ranks(user.id)

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
        return RedirectResponse(url="/login", status_code=303)

    library_item = db.query(LibraryItem).filter(
        LibraryItem.id == item_id,
        LibraryItem.user_id == user.id,
    ).first()

    if library_item:
        db.delete(library_item)
        db.commit()

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
        return RedirectResponse(url="/login", status_code=303)

    existing = db.query(LibraryItem).filter(
        LibraryItem.user_id == user.id,
        LibraryItem.content_id == content_id,
    ).first()

    if existing:
        return RedirectResponse(url="/library", status_code=303)

    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        return RedirectResponse(url="/library", status_code=303)

    status_map = {
        "watching": WatchStatus.WATCHING,
        "planned": WatchStatus.PLANNED,
        "completed": WatchStatus.COMPLETED,
        "dropped": WatchStatus.DROPPED,
        "maybe": WatchStatus.MAYBE,
    }

    library_item = LibraryItem(
        user_id=user.id,
        content_id=content_id,
        status=status_map.get(status, WatchStatus.PLANNED),
    )

    db.add(library_item)
    db.commit()

    return RedirectResponse(url="/library", status_code=303)
