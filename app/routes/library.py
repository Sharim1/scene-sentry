"""
Library routes for tracking content
"""
import logging
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request, Depends, Form, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, LibraryItem, Content, Reminder
from app.models.library import WatchStatus
from app.models.reminder import ReminderType
from app.routes.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def library(
    request: Request,
    type: str = Query("all", alias="type"),
    status: str = Query("all"),
    q: str = Query(None),
    db: Session = Depends(get_db)
):
    """Library page with filtering and search"""
    from app.templates import templates
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Build query
    query = db.query(LibraryItem).filter(LibraryItem.user_id == user.id)
    
    # Always join Content for search and type filter
    query = query.join(Content)
    
    # Search by title
    search_query = q
    if q:
        query = query.filter(
            Content.title.ilike(f"%{q}%") |
            Content.description.ilike(f"%{q}%")
        )
    
    # Filter by content type
    if type != "all":
        query = query.filter(Content.content_type == type)
    
    # Filter by status
    if status != "all":
        status_map = {
            'watching': WatchStatus.WATCHING,
            'planned': WatchStatus.PLANNED,
            'completed': WatchStatus.COMPLETED,
            'dropped': WatchStatus.DROPPED,
            'maybe': WatchStatus.MAYBE
        }
        if status in status_map:
            query = query.filter(LibraryItem.status == status_map[status])
    
    library_items = query.order_by(LibraryItem.updated_at.desc()).all()
    
    # Get counts for tabs
    counts = {
        'all': db.query(LibraryItem).filter(LibraryItem.user_id == user.id).count(),
        'watching': db.query(LibraryItem).filter(
            LibraryItem.user_id == user.id,
            LibraryItem.status == WatchStatus.WATCHING
        ).count(),
        'planned': db.query(LibraryItem).filter(
            LibraryItem.user_id == user.id,
            LibraryItem.status == WatchStatus.PLANNED
        ).count(),
        'completed': db.query(LibraryItem).filter(
            LibraryItem.user_id == user.id,
            LibraryItem.status == WatchStatus.COMPLETED
        ).count(),
        'dropped': db.query(LibraryItem).filter(
            LibraryItem.user_id == user.id,
            LibraryItem.status == WatchStatus.DROPPED
        ).count()
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
            "counts": counts
        }
    )


@router.post("/item/{item_id}/update")
async def update_library_item(
    request: Request,
    item_id: int,
    status: str = Form(...),
    weekly_release: bool = Form(False),
    db: Session = Depends(get_db)
):
    """Update library item status"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    library_item = db.query(LibraryItem).filter(
        LibraryItem.id == item_id,
        LibraryItem.user_id == user.id
    ).first()
    
    if library_item:
        # Map status string to enum
        status_map = {
            'watching': WatchStatus.WATCHING,
            'planned': WatchStatus.PLANNED,
            'completed': WatchStatus.COMPLETED,
            'dropped': WatchStatus.DROPPED,
            'maybe': WatchStatus.MAYBE
        }
        
        new_status = status_map.get(status)
        if new_status:
            old_status = library_item.status
            library_item.status = new_status
            library_item.updated_at = datetime.now(timezone.utc)
            
            # Track start/finish times
            if new_status == WatchStatus.WATCHING and old_status != WatchStatus.WATCHING:
                library_item.started_at = datetime.now(timezone.utc)
            elif new_status == WatchStatus.COMPLETED:
                library_item.finished_at = datetime.now(timezone.utc)
            
            # Handle weekly release tracking
            if new_status == WatchStatus.WATCHING and weekly_release:
                library_item.weekly_release = True
                next_date = datetime.now(timezone.utc) + timedelta(days=7)
                library_item.next_episode_date = next_date
                
                # Create reminder
                reminder = Reminder(
                    user_id=user.id,
                    library_item_id=library_item.id,
                    reminder_type=ReminderType.NEXT_EPISODE,
                    scheduled_time=next_date,
                    message=f"New episode of {library_item.content.title} should be available!"
                )
                db.add(reminder)
            
            db.commit()
    
    return RedirectResponse(url="/library", status_code=303)


@router.post("/item/{item_id}/progress")
async def update_progress(
    request: Request,
    item_id: int,
    progress: int = Form(...),
    season: int = Form(None),
    episode: int = Form(None),
    db: Session = Depends(get_db)
):
    """Update progress on a library item"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    library_item = db.query(LibraryItem).filter(
        LibraryItem.id == item_id,
        LibraryItem.user_id == user.id
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
async def rate_item(
    request: Request,
    item_id: int,
    rating: int = Form(...),
    notes: str = Form(None),
    db: Session = Depends(get_db)
):
    """Rate a library item"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    library_item = db.query(LibraryItem).filter(
        LibraryItem.id == item_id,
        LibraryItem.user_id == user.id
    ).first()
    
    if library_item:
        library_item.rating = min(5, max(1, rating))  # Clamp to 1-5
        if notes:
            library_item.notes = notes
        library_item.updated_at = datetime.now(timezone.utc)
        db.commit()
    
    return RedirectResponse(url="/library", status_code=303)


@router.post("/item/{item_id}/delete")
async def delete_library_item(
    request: Request,
    item_id: int,
    db: Session = Depends(get_db)
):
    """Remove item from library"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    library_item = db.query(LibraryItem).filter(
        LibraryItem.id == item_id,
        LibraryItem.user_id == user.id
    ).first()
    
    if library_item:
        db.delete(library_item)
        db.commit()
    
    return RedirectResponse(url="/library", status_code=303)


@router.post("/add")
async def add_to_library(
    request: Request,
    content_id: int = Form(...),
    status: str = Form("planned"),
    db: Session = Depends(get_db)
):
    """Add content to library"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Check if already in library
    existing = db.query(LibraryItem).filter(
        LibraryItem.user_id == user.id,
        LibraryItem.content_id == content_id
    ).first()
    
    if existing:
        return RedirectResponse(url="/library", status_code=303)
    
    # Verify content exists
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        return RedirectResponse(url="/library", status_code=303)
    
    # Map status
    status_map = {
        'watching': WatchStatus.WATCHING,
        'planned': WatchStatus.PLANNED,
        'completed': WatchStatus.COMPLETED,
        'dropped': WatchStatus.DROPPED,
        'maybe': WatchStatus.MAYBE
    }
    
    library_item = LibraryItem(
        user_id=user.id,
        content_id=content_id,
        status=status_map.get(status, WatchStatus.PLANNED)
    )
    
    db.add(library_item)
    db.commit()
    
    return RedirectResponse(url="/library", status_code=303)

