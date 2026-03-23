"""
JSON API routes for AJAX interactions
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Request, Depends, HTTPException, Query, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Content, LibraryItem, Gossip
from app.models.library import WatchStatus
from app.routes.auth import get_current_user
from app.services.task_manager import get_task_manager, TaskType, TaskStatus

logger = logging.getLogger(__name__)
router = APIRouter()

_running_tasks: set = set()


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
    preview_text: Optional[str]
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


class TaskStartRequest(BaseModel):
    preferences: Optional[str] = None
    query: Optional[str] = None


@router.get("/search", response_model=SearchResponse)
async def search_content(
    request: Request,
    q: str = Query(..., min_length=1),
    type: str = Query(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    from app.repositories.content_repo import ContentRepository
    repo = ContentRepository(db)
    results = repo.search(q, content_type=type, limit=20)

    return SearchResponse(
        query=q,
        results=[
            ContentResponse(
                id=c.id,
                title=c.title,
                content_type=c.content_type,
                poster_url=c.poster_url,
                rating=c.rating,
                year=c.release_date[:4] if c.release_date else None,
            )
            for c in results
        ],
        count=len(results),
    )


@router.get("/library", response_model=List[LibraryItemResponse])
async def get_library(
    request: Request,
    status: str = Query(None),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    from app.repositories.library_repo import LibraryRepository
    ws = None
    if status:
        status_map = {
            "watching": WatchStatus.WATCHING,
            "planned": WatchStatus.PLANNED,
            "completed": WatchStatus.COMPLETED,
            "dropped": WatchStatus.DROPPED,
            "maybe": WatchStatus.MAYBE,
        }
        ws = status_map.get(status)

    repo = LibraryRepository(db)
    items = repo.get_by_user(user.id, status=ws)

    return [
        LibraryItemResponse(
            id=item.id,
            content=ContentResponse(
                id=item.content.id,
                title=item.content.title,
                content_type=item.content.content_type,
                poster_url=item.content.poster_url,
                rating=item.content.rating,
                year=item.content.release_date[:4] if item.content.release_date else None,
            ),
            status=item.status.value,
            progress=item.progress,
            rating=item.rating,
        )
        for item in items
    ]


@router.put("/library/{item_id}/status")
async def update_item_status(
    request: Request, item_id: int, update: StatusUpdate, db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    from app.repositories.library_repo import LibraryRepository
    status_map = {
        "watching": WatchStatus.WATCHING,
        "planned": WatchStatus.PLANNED,
        "completed": WatchStatus.COMPLETED,
        "dropped": WatchStatus.DROPPED,
        "maybe": WatchStatus.MAYBE,
    }
    if update.status not in status_map:
        raise HTTPException(status_code=400, detail="Invalid status")

    repo = LibraryRepository(db)
    item = repo.update_status(item_id, user.id, status_map[update.status])
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    db.commit()

    from app.services.ranking_service import RankingService
    RankingService(db).invalidate_ranks(user.id)

    return {"success": True, "status": update.status}


@router.put("/library/{item_id}/progress")
async def update_item_progress(
    request: Request, item_id: int, update: ProgressUpdate, db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    item = db.query(LibraryItem).filter(
        LibraryItem.id == item_id, LibraryItem.user_id == user.id
    ).first()
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    item.progress = update.progress
    if update.season is not None:
        item.current_season = update.season
    if update.episode is not None:
        item.current_episode = update.episode
    item.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"success": True, "progress": update.progress}


@router.put("/library/{item_id}/rating")
async def update_item_rating(
    request: Request, item_id: int, update: RatingUpdate, db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    from app.repositories.library_repo import LibraryRepository
    repo = LibraryRepository(db)
    item = repo.update_rating(item_id, user.id, update.rating, update.notes)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    db.commit()

    from app.services.ranking_service import RankingService
    RankingService(db).invalidate_ranks(user.id)

    return {"success": True, "rating": item.rating}


@router.get("/gossip/latest", response_model=List[GossipResponse])
async def get_latest_gossip(
    request: Request, limit: int = Query(10, le=50), db: Session = Depends(get_db)
):
    from app.services.gossip_service import GossipService
    svc = GossipService(db)
    items = svc.get_latest(limit=limit)

    return [
        GossipResponse(
            id=g.id,
            title=g.title,
            preview_text=g.preview_text,
            source_name=g.source_name,
            image_url=g.image_url,
            tag=g.tag.value if g.tag else "rumor",
            time_ago=g.time_ago,
        )
        for g in items
    ]


@router.get("/rankings")
async def get_rankings(
    request: Request,
    content_type: str = Query(None),
    limit: int = Query(10, le=50),
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    from app.services.ranking_service import RankingService
    svc = RankingService(db)
    ranked = svc.get_personalized_content(user.id, content_type=content_type, limit=limit)

    return [
        {
            "content": ContentResponse(
                id=content.id,
                title=content.title,
                content_type=content.content_type,
                poster_url=content.poster_url,
                rating=content.rating,
                year=content.release_date[:4] if content.release_date else None,
            ).model_dump(),
            "rank_score": score,
            "reasoning": reasoning,
        }
        for content, score, reasoning in ranked
    ]


# ==================== TASK MANAGEMENT ENDPOINTS ====================

@router.get("/tasks")
async def get_user_tasks(
    request: Request, active_only: bool = Query(True), db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    task_manager = get_task_manager()
    tasks = await task_manager.get_user_tasks(user.id, active_only=active_only)
    return {"tasks": [task.to_dict() for task in tasks]}


@router.get("/tasks/stream")
async def task_stream(request: Request, db: Session = Depends(get_db)):
    user = get_current_user(request, db)
    if not user:
        async def empty_stream():
            yield "data: {}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    task_manager = get_task_manager()
    queue = await task_manager.subscribe(user.id)

    async def event_generator():
        try:
            yield 'data: {"type": "connected"}\n\n'
            while True:
                try:
                    task_data = await asyncio.wait_for(queue.get(), timeout=30.0)
                    yield f"data: {__import__('json').dumps(task_data)}\n\n"
                except asyncio.TimeoutError:
                    yield 'data: {"type": "keepalive"}\n\n'
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
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/tasks/{task_type}/start")
async def start_task(
    request: Request,
    task_type: str,
    background_tasks: BackgroundTasks,
    body: TaskStartRequest = None,
    db: Session = Depends(get_db),
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    task_type_map = {
        "gossip_scrape": TaskType.GOSSIP_SCRAPE,
        "content_reranking": TaskType.CONTENT_RERANKING,
    }

    if task_type not in task_type_map:
        raise HTTPException(status_code=400, detail=f"Invalid task type: {task_type}")

    task_manager = get_task_manager()
    existing_tasks = await task_manager.get_user_tasks(user.id, active_only=True)
    for existing in existing_tasks:
        if existing.type == task_type_map[task_type]:
            return {"success": False, "message": "A task of this type is already running", "task": existing.to_dict()}

    task = await task_manager.create_task(task_type=task_type_map[task_type], user_id=user.id)

    user_id = user.id

    async def run_gossip_scrape(task, tm):
        from app.services.gossip_service import GossipService as GS
        from app.repositories.library_repo import LibraryRepository

        await tm.update_task(task.id, progress=10, message="Gathering tracked content...")
        try:
            db_gen = get_db()
            db_session = next(db_gen)
            try:
                tracked = LibraryRepository(db_session).get_all_tracked_titles()
                await tm.update_task(task.id, progress=30, message=f"Scanning news for {len(tracked)} titles...")
                svc = GS(db_session)
                results = await svc.scrape_latest(tracked)
                await tm.update_task(task.id, progress=90, message=f"Found {len(results)} gossip items")
                return {"scraped": len(results)}
            finally:
                db_session.close()
        except Exception as e:
            logger.error(f"Gossip scrape error: {e}")
            raise

    async def run_content_reranking(task, tm):
        from app.services.ranking_service import RankingService

        await tm.update_task(task.id, progress=10, message="Starting content re-ranking...")
        try:
            db_gen = get_db()
            db_session = next(db_gen)
            try:
                svc = RankingService(db_session)
                count = await svc.run_reranking(user_id)
                await tm.update_task(task.id, progress=90, message=f"Ranked {count} items")
                return {"ranked": count}
            finally:
                db_session.close()
        except Exception as e:
            logger.error(f"Re-ranking error: {e}")
            raise

    task_functions = {
        TaskType.GOSSIP_SCRAPE: run_gossip_scrape,
        TaskType.CONTENT_RERANKING: run_content_reranking,
    }

    task_func = task_functions.get(task_type_map[task_type])

    async def run_and_cleanup():
        try:
            await asyncio.sleep(0.5)
            await task_manager.run_task(task.id, task_func)
        finally:
            _running_tasks.discard(asyncio.current_task())

    bg_task = asyncio.create_task(run_and_cleanup())
    _running_tasks.add(bg_task)

    return {"success": True, "message": f"Task started: {task.name}", "task": task.to_dict()}


@router.post("/tasks/{task_id}/cancel")
async def cancel_task(
    request: Request, task_id: str, db: Session = Depends(get_db)
):
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    task_manager = get_task_manager()
    task = await task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    success = await task_manager.cancel_task(task_id)
    return {"success": success}
