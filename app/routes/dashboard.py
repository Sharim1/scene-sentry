"""
Dashboard routes
"""
import os
import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Request, Depends, Form, BackgroundTasks
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
    background_tasks: BackgroundTasks,
    query: str = Form(...),
    db: Session = Depends(get_db)
):
    """Search for content using AI with background task"""
    from app.services.task_manager import get_task_manager, TaskType
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    task_manager = get_task_manager()
    
    # Check for existing AI search task
    existing_tasks = await task_manager.get_user_tasks(user.id, active_only=True)
    for existing in existing_tasks:
        if existing.type == TaskType.AI_SEARCH:
            logger.info(f"AI search already running for user {user.id}")
            return RedirectResponse(url="/dashboard", status_code=303)
    
    # Create and run task
    task = await task_manager.create_task(
        task_type=TaskType.AI_SEARCH,
        user_id=user.id,
        name=f"Searching: {query[:30]}..."
    )
    
    async def run_ai_search(task, tm):
        from app.agents.graph import discovery_graph
        
        await tm.update_task(task.id, progress=10, message="Analyzing your query...")
        
        try:
            await tm.update_task(task.id, progress=30, message="Searching web sources...")
            
            results = await discovery_graph.run_discovery(user.id, search_query=query)
            
            await tm.update_task(task.id, progress=90, message=f"Found {len(results)} recommendations")
            
            return {"recommendations": len(results), "query": query}
            
        except Exception as e:
            logger.error(f"AI search error: {e}")
            raise
    
    background_tasks.add_task(task_manager.run_task, task.id, run_ai_search)
    logger.info(f"Started AI search task {task.id} for user {user.id}")
    
    return RedirectResponse(url="/dashboard", status_code=303)


@router.post("/discover")
async def force_discovery(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Force AI discovery for user with background task"""
    from app.services.task_manager import get_task_manager, TaskType
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    task_manager = get_task_manager()
    
    # Check for existing recommendation task
    existing_tasks = await task_manager.get_user_tasks(user.id, active_only=True)
    for existing in existing_tasks:
        if existing.type == TaskType.CONTENT_RECOMMENDATION:
            logger.info(f"Content recommendation already running for user {user.id}")
            return RedirectResponse(url="/dashboard", status_code=303)
    
    # Create and run task
    task = await task_manager.create_task(
        task_type=TaskType.CONTENT_RECOMMENDATION,
        user_id=user.id,
        name="Generating Recommendations"
    )
    
    async def run_discovery(task, tm):
        from app.agents.graph import discovery_graph
        
        await tm.update_task(task.id, progress=10, message="Analyzing your preferences...")
        
        try:
            await tm.update_task(task.id, progress=30, message="Searching for content...")
            
            results = await discovery_graph.run_discovery(user.id)
            
            await tm.update_task(task.id, progress=90, message=f"Generated {len(results)} recommendations")
            
            return {"recommendations": len(results)}
            
        except Exception as e:
            logger.error(f"Discovery error: {e}")
            raise
    
    background_tasks.add_task(task_manager.run_task, task.id, run_discovery)
    logger.info(f"Started discovery task {task.id} for user {user.id}")
    
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

