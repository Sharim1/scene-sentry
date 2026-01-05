"""
Dashboard routes
"""
import os
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.database import get_db
from app.models import User, Recommendation, LibraryItem, Reminder, Gossip, Content
from app.models.library import WatchStatus
from app.routes.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


def get_ai_agent_status():
    """Get the current AI agent status based on configuration"""
    tavily_key = os.environ.get("TAVILY_API_KEY")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    
    if not tavily_key:
        return {
            "status": "inactive",
            "message": "Tavily API key not configured",
            "details": "Add TAVILY_API_KEY to .env to enable gossip scraping",
            "color": "yellow"
        }
    
    if not gemini_key:
        return {
            "status": "limited",
            "message": "Gossip scraping enabled",
            "details": "Add GEMINI_API_KEY for AI-powered analysis",
            "color": "blue"
        }
    
    return {
        "status": "active",
        "message": "AI agents fully operational",
        "details": "Scraping variety.com, deadline.com...",
        "color": "green"
    }


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """Main dashboard page"""
    from app.main import templates
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Get recent recommendations
    recommendations = db.query(Recommendation).filter(
        Recommendation.user_id == user.id,
        Recommendation.dismissed == False
    ).order_by(Recommendation.confidence_score.desc()).limit(10).all()
    
    # Get library stats
    library_stats = {
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
        'maybe': db.query(LibraryItem).filter(
            LibraryItem.user_id == user.id,
            LibraryItem.status == WatchStatus.MAYBE
        ).count()
    }
    
    # Get upcoming reminders
    upcoming_reminders = db.query(Reminder).filter(
        Reminder.user_id == user.id,
        Reminder.sent == False,
        Reminder.scheduled_time <= datetime.utcnow() + timedelta(days=7)
    ).order_by(Reminder.scheduled_time).limit(5).all()
    
    # Get latest gossip
    latest_gossip = db.query(Gossip).filter(
        Gossip.is_active == True
    ).order_by(Gossip.scraped_at.desc()).limit(6).all()
    
    # Get featured gossip (for hero section)
    featured_gossip = db.query(Gossip).filter(
        Gossip.is_featured == True,
        Gossip.is_active == True
    ).order_by(Gossip.scraped_at.desc()).first()
    
    # Get trending content (most added to libraries recently)
    trending = db.query(Content).join(LibraryItem).filter(
        LibraryItem.added_at >= datetime.utcnow() - timedelta(days=7)
    ).group_by(Content.id).order_by(
        func.count(LibraryItem.id).desc()
    ).limit(5).all()
    
    # Get AI agent status
    ai_status = get_ai_agent_status()
    
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "recommendations": recommendations,
            "library_stats": library_stats,
            "upcoming_reminders": upcoming_reminders,
            "latest_gossip": latest_gossip,
            "featured_gossip": featured_gossip,
            "trending": trending,
            "ai_status": ai_status
        }
    )


@router.post("/search")
async def search_content(
    request: Request,
    query: str = Form(...),
    db: Session = Depends(get_db)
):
    """Search for content using AI"""
    import asyncio
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    try:
        from app.agents.graph import discovery_graph
        
        # Run discovery with search query
        async def run_with_timeout():
            return await discovery_graph.run_discovery(user.id, search_query=query)
        
        results = await asyncio.wait_for(run_with_timeout(), timeout=18.0)
        
        logger.info(f"Search completed for user {user.id}: {len(results)} results")
        
    except asyncio.TimeoutError:
        logger.warning(f"Search timeout for user {user.id}, query: {query}")
    except Exception as e:
        logger.error(f"Error in search: {e}")
    
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/discover")
async def force_discovery(request: Request, db: Session = Depends(get_db)):
    """Force AI discovery for user"""
    import asyncio
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    try:
        from app.agents.graph import discovery_graph
        
        async def run_with_timeout():
            return await discovery_graph.run_discovery(user.id)
        
        results = await asyncio.wait_for(run_with_timeout(), timeout=20.0)
        
        logger.info(f"Discovery completed for user {user.id}: {len(results)} results")
        
    except asyncio.TimeoutError:
        logger.warning(f"Discovery timeout for user {user.id}")
    except Exception as e:
        logger.error(f"Error in discovery: {e}")
    
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/recommendation/{rec_id}/add")
async def add_to_library(
    request: Request,
    rec_id: int,
    status: str = Form(...),
    db: Session = Depends(get_db)
):
    """Add recommendation to library"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    recommendation = db.query(Recommendation).filter(
        Recommendation.id == rec_id,
        Recommendation.user_id == user.id
    ).first()
    
    if recommendation:
        # Check if already in library
        existing = db.query(LibraryItem).filter(
            LibraryItem.user_id == user.id,
            LibraryItem.content_id == recommendation.content_id
        ).first()
        
        # Map status string to enum
        status_map = {
            'watching': WatchStatus.WATCHING,
            'planned': WatchStatus.PLANNED,
            'completed': WatchStatus.COMPLETED,
            'dropped': WatchStatus.DROPPED,
            'maybe': WatchStatus.MAYBE,
            'confirmed': WatchStatus.PLANNED,  # Legacy support
            'in_progress': WatchStatus.WATCHING  # Legacy support
        }
        watch_status = status_map.get(status, WatchStatus.PLANNED)
        
        if existing:
            existing.status = watch_status
            existing.updated_at = datetime.utcnow()
        else:
            library_item = LibraryItem(
                user_id=user.id,
                content_id=recommendation.content_id,
                status=watch_status
            )
            db.add(library_item)
        
        # Mark recommendation as saved
        recommendation.viewed = True
        recommendation.saved_to_library = True
        db.commit()
    
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/recommendation/{rec_id}/dismiss")
async def dismiss_recommendation(
    request: Request,
    rec_id: int,
    db: Session = Depends(get_db)
):
    """Dismiss a recommendation"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    recommendation = db.query(Recommendation).filter(
        Recommendation.id == rec_id,
        Recommendation.user_id == user.id
    ).first()
    
    if recommendation:
        recommendation.dismissed = True
        db.commit()
    
    return RedirectResponse(url="/dashboard", status_code=303)

