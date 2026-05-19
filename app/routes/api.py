"""
JSON API routes for AJAX interactions
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Annotated, Any, List, Optional

from fastapi import APIRouter, Body, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from app.database import get_db
from app.dependencies import DbDep, OptionalUserDep, RequireAuthDep
from app.models import LibraryItem
from app.models.library import WatchStatus
from app.services.task_manager import get_task_manager, TaskType

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["api"])

_running_tasks: set = set()


class ContentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content_type: str
    poster_url: Optional[str]
    rating: Optional[float]
    year: Optional[str]


class GossipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    preview_text: Optional[str]
    source_name: str
    image_url: Optional[str]
    tag: str
    time_ago: str


class LibraryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: ContentResponse
    status: str
    progress: int
    rating: Optional[int]


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


class LibraryMutationResponse(BaseModel):
    success: bool
    status: Optional[str] = None
    progress: Optional[int] = None
    rating: Optional[int] = None


class RankedItemResponse(BaseModel):
    content: ContentResponse
    rank_score: Optional[float]
    reasoning: Optional[str]


class TaskPayload(BaseModel):
    id: str
    type: str
    name: str
    user_id: int
    status: str
    progress: int
    message: str
    result: Optional[dict[str, Any]] = None
    error: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None


class TaskListResponse(BaseModel):
    tasks: List[TaskPayload]


class TaskActionResponse(BaseModel):
    success: bool
    message: Optional[str] = None
    task: Optional[TaskPayload] = None


class TaskCancelResponse(BaseModel):
    success: bool


@router.get("/search", response_model=SearchResponse)
def search_content(
    user: RequireAuthDep,
    db: DbDep,
    q: Annotated[str, Query(min_length=1)],
    type: Annotated[str | None, Query()] = None,
):
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
def get_library(
    user: RequireAuthDep,
    db: DbDep,
    status: Annotated[str | None, Query()] = None,
):

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


@router.put(
    "/library/{item_id}/status",
    response_model=LibraryMutationResponse,
)
def update_item_status(
    item_id: int,
    update: StatusUpdate,
    user: RequireAuthDep,
    db: DbDep,
):

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

    return LibraryMutationResponse(success=True, status=update.status)


@router.put(
    "/library/{item_id}/progress",
    response_model=LibraryMutationResponse,
)
def update_item_progress(
    item_id: int,
    update: ProgressUpdate,
    user: RequireAuthDep,
    db: DbDep,
):

    item = db.query(LibraryItem).filter(
        LibraryItem.id == item_id,
        LibraryItem.user_id == user.id,
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
    return LibraryMutationResponse(success=True, progress=update.progress)


@router.put(
    "/library/{item_id}/rating",
    response_model=LibraryMutationResponse,
)
def update_item_rating(
    item_id: int,
    update: RatingUpdate,
    user: RequireAuthDep,
    db: DbDep,
):

    from app.repositories.library_repo import LibraryRepository

    repo = LibraryRepository(db)
    item = repo.update_rating(item_id, user.id, update.rating, update.notes)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    db.commit()

    from app.services.ranking_service import RankingService

    RankingService(db).invalidate_ranks(user.id)

    return LibraryMutationResponse(success=True, rating=item.rating)


@router.get("/gossip/latest", response_model=List[GossipResponse])
def get_latest_gossip(
    request: Request,
    db: DbDep,
    limit: Annotated[int, Query(le=50)] = 10,
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


@router.get("/rankings", response_model=list[RankedItemResponse])
def get_rankings(
    user: RequireAuthDep,
    db: DbDep,
    content_type: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(le=50)] = 10,
):

    from app.services.ranking_service import RankingService

    svc = RankingService(db)
    ranked = svc.get_personalized_content(
        user.id, content_type=content_type, limit=limit
    )

    return [
        RankedItemResponse(
            content=ContentResponse(
                id=content.id,
                title=content.title,
                content_type=content.content_type,
                poster_url=content.poster_url,
                rating=content.rating,
                year=content.release_date[:4] if content.release_date else None,
            ),
            rank_score=score,
            reasoning=reasoning,
        )
        for content, score, reasoning in ranked
    ]


# ==================== TASK MANAGEMENT ENDPOINTS ====================


@router.get("/tasks", response_model=TaskListResponse)
async def get_user_tasks(
    user: RequireAuthDep,
    active_only: Annotated[bool, Query()] = True,
):

    task_manager = get_task_manager()
    tasks = await task_manager.get_user_tasks(user.id, active_only=active_only)
    return TaskListResponse(
        tasks=[TaskPayload.model_validate(t.to_dict()) for t in tasks]
    )


@router.get("/tasks/stream")
async def task_stream(request: Request, user: OptionalUserDep):
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
                    yield f"data: {json.dumps(task_data)}\n\n"
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


@router.post(
    "/tasks/{task_type}/start",
    response_model=TaskActionResponse,
)
async def start_task(
    task_type: str,
    user: RequireAuthDep,
    db: DbDep,
    body: Annotated[TaskStartRequest | None, Body()] = None,
):
    _ = body

    task_type_map = {
        "gossip_scrape": TaskType.GOSSIP_SCRAPE,
        "content_reranking": TaskType.CONTENT_RERANKING,
    }

    if task_type not in task_type_map:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task type: {task_type}",
        )

    task_manager = get_task_manager()
    existing_tasks = await task_manager.get_user_tasks(user.id, active_only=True)
    for existing in existing_tasks:
        if existing.type == task_type_map[task_type]:
            return TaskActionResponse(
                success=False,
                message="A task of this type is already running",
                task=TaskPayload.model_validate(existing.to_dict()),
            )

    task = await task_manager.create_task(
        task_type=task_type_map[task_type],
        user_id=user.id,
    )

    user_id = user.id

    async def run_gossip_scrape(task, tm):
        from app.repositories.library_repo import LibraryRepository
        from app.services.gossip_service import GossipService as GS

        await tm.update_task(task.id, progress=10, message="Gathering tracked content...")
        try:
            db_gen = get_db()
            db_session = next(db_gen)
            try:
                tracked = LibraryRepository(db_session).get_all_tracked_titles()
                await tm.update_task(
                    task.id,
                    progress=30,
                    message=f"Scanning news for {len(tracked)} titles...",
                )
                svc = GS(db_session)
                results = await svc.scrape_latest(tracked)
                await tm.update_task(
                    task.id,
                    progress=90,
                    message=f"Found {len(results)} gossip items",
                )
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
                await tm.update_task(
                    task.id,
                    progress=90,
                    message=f"Ranked {count} items",
                )
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

    return TaskActionResponse(
        success=True,
        message=f"Task started: {task.name}",
        task=TaskPayload.model_validate(task.to_dict()),
    )


@router.post("/tasks/{task_id}/cancel", response_model=TaskCancelResponse)
async def cancel_task(
    task_id: str,
    user: RequireAuthDep,
):

    task_manager = get_task_manager()
    task = await task_manager.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    success = await task_manager.cancel_task(task_id)
    return TaskCancelResponse(success=success)
