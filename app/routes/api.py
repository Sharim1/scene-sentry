"""
JSON API routes for AJAX interactions
"""
import logging
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Request, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Content, LibraryItem, Recommendation, Gossip
from app.models.library import WatchStatus
from app.routes.auth import get_current_user

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

