"""
JSON API routes for AJAX interactions
"""

import logging
from typing import Annotated

import pydantic
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict

from app.config import settings
from app.dependencies import DbDep, RequireAuthDep
from app.routes.auth import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["api"])


class ContentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    content_type: str
    poster_url: str | None
    rating: float | None
    year: str | None


class GossipResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    preview_text: str | None
    source_name: str
    source_url: str | None
    image_url: str | None
    tag: str
    time_ago: str
    scraped_at: str | None


class LibraryItemResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    content: ContentResponse
    status: str
    progress: int
    rating: int | None


class SearchResponse(BaseModel):
    query: str
    results: list[ContentResponse]
    count: int


class StatusUpdate(BaseModel):
    status: str


class ProgressUpdate(BaseModel):
    progress: int = pydantic.Field(ge=0, le=100)
    season: int | None = None
    episode: int | None = None


class RatingUpdate(BaseModel):
    rating: int
    notes: str | None = None


class AddToLibraryRequest(BaseModel):
    content_id: int
    status: str = "planned"


class LibraryMutationResponse(BaseModel):
    success: bool
    item_id: int | None = None
    status: str | None = None
    progress: int | None = None
    rating: int | None = None


class RankedItemResponse(BaseModel):
    content: ContentResponse
    rank_score: float | None
    reasoning: str | None


@router.get("/search", response_model=SearchResponse)
@limiter.limit(settings.rate_limit_api)
def search_content(
    request: Request,
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


@router.get("/library", response_model=list[LibraryItemResponse])
def get_library(
    user: RequireAuthDep,
    db: DbDep,
    status: Annotated[str | None, Query()] = None,
):
    from app.models.library import WatchStatus as WS
    from app.repositories.library_repo import LibraryRepository

    ws = None
    if status:
        status_map = {
            "watching": WS.WATCHING,
            "planned": WS.PLANNED,
            "completed": WS.COMPLETED,
            "dropped": WS.DROPPED,
            "maybe": WS.MAYBE,
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


@router.post("/library", response_model=LibraryMutationResponse)
def add_to_library_api(
    body: AddToLibraryRequest,
    user: RequireAuthDep,
    db: DbDep,
):
    from app.repositories.library_repo import LibraryRepository
    from app.services.library_service import LibraryService

    repo = LibraryRepository(db)
    existing = repo.get_by_user_and_content(user.id, body.content_id)

    svc = LibraryService(db)
    if existing:
        item = svc.update_status(user.id, existing.id, body.status)
    else:
        item = svc.add(user.id, body.content_id, body.status)

    if not item:
        raise HTTPException(status_code=400, detail="Content not found or invalid status")

    return LibraryMutationResponse(
        success=True,
        item_id=item.id,
        status=item.status.value,
    )


@router.delete("/library/{item_id}", response_model=LibraryMutationResponse)
def remove_from_library_api(
    item_id: int,
    user: RequireAuthDep,
    db: DbDep,
):
    from app.services.library_service import LibraryService

    svc = LibraryService(db)
    deleted = svc.delete(user.id, item_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Item not found")

    return LibraryMutationResponse(success=True)


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
    from app.services.library_service import LibraryService

    svc = LibraryService(db)
    item = svc.update_status(user.id, item_id, update.status)
    if not item:
        raise HTTPException(status_code=400, detail="Invalid status or item not found")

    return LibraryMutationResponse(success=True, item_id=item.id, status=item.status.value)


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
    from app.services.library_service import LibraryService

    svc = LibraryService(db)
    item = svc.update_progress(user.id, item_id, update.progress, season=update.season, episode=update.episode)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    return LibraryMutationResponse(success=True, progress=item.progress)


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
    from app.services.library_service import LibraryService

    svc = LibraryService(db)
    item = svc.rate(user.id, item_id, update.rating, notes=update.notes)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    return LibraryMutationResponse(success=True, rating=item.rating)


@router.get("/gossip/latest", response_model=list[GossipResponse])
@limiter.limit(settings.rate_limit_api)
def get_latest_gossip(
    request: Request,
    db: DbDep,
    limit: Annotated[int, Query(le=50)] = 10,
    since: Annotated[str | None, Query()] = None,
):
    from datetime import datetime

    from app.repositories.gossip_repo import GossipRepository

    repo = GossipRepository(db)

    since_dt = None
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
        except ValueError:
            pass

    items = repo.get_latest(limit=limit, since=since_dt)

    return [
        GossipResponse(
            id=g.id,
            title=g.title,
            preview_text=g.preview_text,
            source_name=g.source_name,
            source_url=g.source_url,
            image_url=g.image_url,
            tag=g.tag.value if g.tag else "rumor",
            time_ago=g.time_ago,
            scraped_at=g.scraped_at.isoformat() if g.scraped_at else None,
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

    from app.repositories.ranking_repo import RankingRepository

    repo = RankingRepository(db)
    ranked = repo.get_ranked_content(user.id, content_type=content_type, limit=limit)

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
