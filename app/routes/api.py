"""
JSON API routes for AJAX interactions
"""
import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Request, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Content, LibraryItem, Recommendation, Gossip
from app.models.library import WatchStatus
from app.routes.auth import get_current_user
from app.services.task_manager import get_task_manager, TaskType, TaskStatus

logger = logging.getLogger(__name__)
router = APIRouter()


# Pydantic models for API responses
class ContentResponse(BaseModel):
    id: int
    title: str
    content_type: str
    poster_url: Optional[str]
    rating: Optional[float]
    year: Optional[str]

    class Config:
        from_attributes = True


class GossipResponse(BaseModel):
    id: int
    title: str
    summary: Optional[str]
    source_name: str
    image_url: Optional[str]
    tag: str
    time_ago: str

    class Config:
        from_attributes = True


class LibraryItemResponse(BaseModel):
    id: int
    content: ContentResponse
    status: str
    progress: int
    rating: Optional[int]

    class Config:
        from_attributes = True


class SearchResponse(BaseModel):
    query: str
    results: List[ContentResponse]
    count: int


class StatusUpdate(BaseModel):
    status: str


class ProgressUpdate(BaseModel):
    progress: int
    season: Optional[int] = None
    episode: Optional[int] = None


class RatingUpdate(BaseModel):
    rating: int
    notes: Optional[str] = None


# API Routes
@router.get("/search", response_model=SearchResponse)
async def search_content(
    request: Request,
    q: str = Query(..., min_length=1),
    type: str = Query(None),
    db: Session = Depends(get_db)
):
    """Search content in database"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    query = db.query(Content).filter(
        Content.title.ilike(f"%{q}%")
    )
    
    if type:
        query = query.filter(Content.content_type == type)
    
    results = query.limit(20).all()
    
    return SearchResponse(
        query=q,
        results=[
            ContentResponse(
                id=c.id,
                title=c.title,
                content_type=c.content_type,
                poster_url=c.poster_url,
                rating=c.rating,
                year=c.release_date[:4] if c.release_date else None
            )
            for c in results
        ],
        count=len(results)
    )


@router.get("/library", response_model=List[LibraryItemResponse])
async def get_library(
    request: Request,
    status: str = Query(None),
    db: Session = Depends(get_db)
):
    """Get user's library items"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    query = db.query(LibraryItem).filter(LibraryItem.user_id == user.id)
    
    if status:
        status_map = {
            'watching': WatchStatus.WATCHING,
            'planned': WatchStatus.PLANNED,
            'completed': WatchStatus.COMPLETED,
            'dropped': WatchStatus.DROPPED,
            'maybe': WatchStatus.MAYBE
        }
        if status in status_map:
            query = query.filter(LibraryItem.status == status_map[status])
    
    items = query.order_by(LibraryItem.updated_at.desc()).all()
    
    return [
        LibraryItemResponse(
            id=item.id,
            content=ContentResponse(
                id=item.content.id,
                title=item.content.title,
                content_type=item.content.content_type,
                poster_url=item.content.poster_url,
                rating=item.content.rating,
                year=item.content.release_date[:4] if item.content.release_date else None
            ),
            status=item.status.value,
            progress=item.progress,
            rating=item.rating
        )
        for item in items
    ]


@router.put("/library/{item_id}/status")
async def update_item_status(
    request: Request,
    item_id: int,
    update: StatusUpdate,
    db: Session = Depends(get_db)
):
    """Update library item status via API"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    item = db.query(LibraryItem).filter(
        LibraryItem.id == item_id,
        LibraryItem.user_id == user.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    status_map = {
        'watching': WatchStatus.WATCHING,
        'planned': WatchStatus.PLANNED,
        'completed': WatchStatus.COMPLETED,
        'dropped': WatchStatus.DROPPED,
        'maybe': WatchStatus.MAYBE
    }
    
    if update.status not in status_map:
        raise HTTPException(status_code=400, detail="Invalid status")
    
    item.status = status_map[update.status]
    item.updated_at = datetime.utcnow()
    db.commit()
    
    return {"success": True, "status": update.status}


@router.put("/library/{item_id}/progress")
async def update_item_progress(
    request: Request,
    item_id: int,
    update: ProgressUpdate,
    db: Session = Depends(get_db)
):
    """Update library item progress via API"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    item = db.query(LibraryItem).filter(
        LibraryItem.id == item_id,
        LibraryItem.user_id == user.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    item.progress = update.progress
    if update.season is not None:
        item.current_season = update.season
    if update.episode is not None:
        item.current_episode = update.episode
    item.updated_at = datetime.utcnow()
    db.commit()
    
    return {"success": True, "progress": update.progress}


@router.put("/library/{item_id}/rating")
async def update_item_rating(
    request: Request,
    item_id: int,
    update: RatingUpdate,
    db: Session = Depends(get_db)
):
    """Update library item rating via API"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    item = db.query(LibraryItem).filter(
        LibraryItem.id == item_id,
        LibraryItem.user_id == user.id
    ).first()
    
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    item.rating = min(5, max(1, update.rating))
    if update.notes:
        item.notes = update.notes
    item.updated_at = datetime.utcnow()
    db.commit()
    
    return {"success": True, "rating": item.rating}


@router.get("/gossip/latest", response_model=List[GossipResponse])
async def get_latest_gossip(
    request: Request,
    limit: int = Query(10, le=50),
    db: Session = Depends(get_db)
):
    """Get latest gossip items"""
    gossip_items = db.query(Gossip).filter(
        Gossip.is_active == True
    ).order_by(Gossip.scraped_at.desc()).limit(limit).all()
    
    return [
        GossipResponse(
            id=g.id,
            title=g.title,
            summary=g.summary,
            source_name=g.source_name,
            image_url=g.image_url,
            tag=g.tag.value if g.tag else "rumor",
            time_ago=g.time_ago
        )
        for g in gossip_items
    ]


@router.get("/recommendations", response_model=List[ContentResponse])
async def get_recommendations(
    request: Request,
    limit: int = Query(10, le=50),
    db: Session = Depends(get_db)
):
    """Get user's recommendations"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    recommendations = db.query(Recommendation).filter(
        Recommendation.user_id == user.id,
        Recommendation.dismissed == False
    ).order_by(Recommendation.confidence_score.desc()).limit(limit).all()
    
    return [
        ContentResponse(
            id=r.content.id,
            title=r.content.title,
            content_type=r.content.content_type,
            poster_url=r.content.poster_url,
            rating=r.content.rating,
            year=r.content.release_date[:4] if r.content.release_date else None
        )
        for r in recommendations
    ]


@router.delete("/recommendations/{rec_id}")
async def dismiss_recommendation(
    request: Request,
    rec_id: int,
    db: Session = Depends(get_db)
):
    """Dismiss a recommendation via API"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    rec = db.query(Recommendation).filter(
        Recommendation.id == rec_id,
        Recommendation.user_id == user.id
    ).first()
    
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    
    rec.dismissed = True
    db.commit()
    
    return {"success": True}


# ==================== TASK MANAGEMENT ENDPOINTS ====================

class TaskStartRequest(BaseModel):
    """Request body for starting a task"""
    preferences: Optional[str] = None
    query: Optional[str] = None


@router.get("/tasks")
async def get_user_tasks(
    request: Request,
    active_only: bool = Query(True),
    db: Session = Depends(get_db)
):
    """Get all tasks for the current user"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    task_manager = get_task_manager()
    tasks = await task_manager.get_user_tasks(user.id, active_only=active_only)
    
    return {"tasks": [task.to_dict() for task in tasks]}


@router.get("/tasks/stream")
async def task_stream(request: Request, db: Session = Depends(get_db)):
    """
    Server-Sent Events endpoint for real-time task updates.
    Clients should connect to this endpoint to receive task status updates.
    """
    user = get_current_user(request, db)
    if not user:
        # Return empty stream for unauthenticated users
        async def empty_stream():
            yield "data: {}\n\n"
        return StreamingResponse(
            empty_stream(),
            media_type="text/event-stream"
        )
    
    task_manager = get_task_manager()
    queue = await task_manager.subscribe(user.id)
    
    async def event_generator():
        """Generate SSE events from task updates"""
        try:
            # Send initial keepalive
            yield "data: {\"type\": \"connected\"}\n\n"
            
            while True:
                try:
                    # Wait for task updates with timeout
                    task_data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {__import__('json').dumps(task_data)}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive to prevent connection timeout
                    yield "data: {\"type\": \"keepalive\"}\n\n"
                except asyncio.CancelledError:
                    break
        finally:
            await task_manager.unsubscribe(user.id, queue)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.post("/tasks/{task_type}/start")
async def start_task(
    request: Request,
    task_type: str,
    background_tasks: BackgroundTasks,
    body: TaskStartRequest = None,
    db: Session = Depends(get_db)
):
    """Start a background task"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    # Map task type string to enum
    task_type_map = {
        "movie_discovery": TaskType.MOVIE_DISCOVERY,
        "tv_discovery": TaskType.TV_DISCOVERY,
        "gossip_scrape": TaskType.GOSSIP_SCRAPE,
        "ai_search": TaskType.AI_SEARCH,
        "content_recommendation": TaskType.CONTENT_RECOMMENDATION,
    }
    
    if task_type not in task_type_map:
        raise HTTPException(status_code=400, detail=f"Invalid task type: {task_type}")
    
    task_manager = get_task_manager()
    
    # Check if user already has an active task of this type
    existing_tasks = await task_manager.get_user_tasks(user.id, active_only=True)
    for existing in existing_tasks:
        if existing.type == task_type_map[task_type]:
            return {
                "success": False,
                "message": "A task of this type is already running",
                "task": existing.to_dict()
            }
    
    # Create the task
    task = await task_manager.create_task(
        task_type=task_type_map[task_type],
        user_id=user.id
    )
    
    # Define task functions for each type
    async def run_movie_discovery(task, tm):
        from app.services.content_scraper import get_content_scraper
        from app.routes.content import save_scraped_content
        
        scraper = get_content_scraper()
        preferences = body.preferences if body else user.preferred_genres or "popular"
        
        await tm.update_task(task.id, progress=10, message="Fetching movie data...")
        
        try:
            movies = await scraper.discover_movies(preferences=preferences, limit=30)
            await tm.update_task(task.id, progress=50, message=f"Found {len(movies)} movies, saving...")
            
            saved_count = 0
            for i, movie_data in enumerate(movies):
                try:
                    with next(get_db()) as db_session:
                        content = await save_scraped_content(db_session, movie_data, "movie")
                        if content:
                            saved_count += 1
                except Exception as e:
                    logger.warning(f"Failed to save movie: {e}")
                
                progress = 50 + int((i / len(movies)) * 40)
                await tm.update_task(task.id, progress=progress)
            
            return {"saved": saved_count, "total": len(movies)}
            
        except Exception as e:
            logger.error(f"Movie discovery error: {e}")
            raise
    
    async def run_tv_discovery(task, tm):
        from app.services.content_scraper import get_content_scraper
        from app.routes.content import save_scraped_content
        
        scraper = get_content_scraper()
        preferences = body.preferences if body else user.preferred_genres or "popular"
        
        await tm.update_task(task.id, progress=10, message="Fetching TV show data...")
        
        try:
            shows = await scraper.discover_tv_shows(preferences=preferences, limit=30)
            await tm.update_task(task.id, progress=50, message=f"Found {len(shows)} TV shows, saving...")
            
            saved_count = 0
            for i, show_data in enumerate(shows):
                try:
                    with next(get_db()) as db_session:
                        content = await save_scraped_content(db_session, show_data, "tv_show")
                        if content:
                            saved_count += 1
                except Exception as e:
                    logger.warning(f"Failed to save TV show: {e}")
                
                progress = 50 + int((i / len(shows)) * 40)
                await tm.update_task(task.id, progress=progress)
            
            return {"saved": saved_count, "total": len(shows)}
            
        except Exception as e:
            logger.error(f"TV discovery error: {e}")
            raise
    
    async def run_gossip_scrape(task, tm):
        from app.agents.gossip_agent import get_gossip_agent
        from app.models import LibraryItem
        from app.models.library import WatchStatus
        
        await tm.update_task(task.id, progress=10, message="Gathering tracked content...")
        
        try:
            # Get user's tracked titles
            tracked_titles = []
            with next(get_db()) as db_session:
                items = db_session.query(LibraryItem).filter(
                    LibraryItem.user_id == user.id,
                    LibraryItem.status.in_([WatchStatus.WATCHING, WatchStatus.PLANNED])
                ).all()
                
                for item in items:
                    if item.content:
                        tracked_titles.append(item.content.title)
            
            await tm.update_task(task.id, progress=30, message=f"Scanning news for {len(tracked_titles)} tracked titles...")
            
            agent = get_gossip_agent()
            results = await agent.scrape_gossip(tracked_titles[:10])
            
            await tm.update_task(task.id, progress=90, message=f"Found {len(results)} gossip items")
            
            return {"scraped": len(results), "tracked_titles": len(tracked_titles)}
            
        except Exception as e:
            logger.error(f"Gossip scrape error: {e}")
            raise
    
    async def run_ai_search(task, tm):
        from app.agents.graph import discovery_graph
        
        query = body.query if body else None
        
        await tm.update_task(task.id, progress=10, message="Starting AI search...")
        
        try:
            results = await discovery_graph.run_discovery(user.id, search_query=query)
            
            await tm.update_task(task.id, progress=90, message=f"Found {len(results)} recommendations")
            
            return {"recommendations": len(results)}
            
        except Exception as e:
            logger.error(f"AI search error: {e}")
            raise
    
    # Map task types to functions
    task_functions = {
        TaskType.MOVIE_DISCOVERY: run_movie_discovery,
        TaskType.TV_DISCOVERY: run_tv_discovery,
        TaskType.GOSSIP_SCRAPE: run_gossip_scrape,
        TaskType.AI_SEARCH: run_ai_search,
        TaskType.CONTENT_RECOMMENDATION: run_ai_search,  # Same as AI search for now
    }
    
    task_func = task_functions.get(task_type_map[task_type])
    
    # Run task in background
    background_tasks.add_task(task_manager.run_task, task.id, task_func)
    
    return {
        "success": True,
        "message": f"Task started: {task.name}",
        "task": task.to_dict()
    }


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    request: Request,
    task_id: str,
    db: Session = Depends(get_db)
):
    """Cancel a running task"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    task_manager = get_task_manager()
    task = await task_manager.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    if task.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized to cancel this task")
    
    success = await task_manager.cancel_task(task_id)
    
    return {"success": success}

