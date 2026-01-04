"""
Gossip routes for entertainment news
"""
import logging
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Gossip, Content
from app.models.gossip import GossipTag
from app.routes.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_class=HTMLResponse)
async def gossip_feed(
    request: Request,
    tag: str = Query(None),
    db: Session = Depends(get_db)
):
    """Main gossip feed page"""
    from app.main import templates
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Build query
    query = db.query(Gossip).filter(Gossip.is_active == True)
    
    # Filter by tag
    if tag:
        try:
            gossip_tag = GossipTag(tag)
            query = query.filter(Gossip.tag == gossip_tag)
        except ValueError:
            pass
    
    gossip_items = query.order_by(Gossip.scraped_at.desc()).limit(50).all()
    
    # Get all available tags with counts
    tag_counts = {}
    for t in GossipTag:
        count = db.query(Gossip).filter(
            Gossip.is_active == True,
            Gossip.tag == t
        ).count()
        if count > 0:
            tag_counts[t.value] = count
    
    return templates.TemplateResponse(
        "gossip/feed.html",
        {
            "request": request,
            "user": user,
            "gossip_items": gossip_items,
            "current_tag": tag,
            "tag_counts": tag_counts,
            "all_tags": [t.value for t in GossipTag]
        }
    )


@router.get("/{gossip_id}", response_class=HTMLResponse)
async def gossip_detail(
    request: Request,
    gossip_id: int,
    db: Session = Depends(get_db)
):
    """Single gossip article page"""
    from app.main import templates
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    gossip = db.query(Gossip).filter(
        Gossip.id == gossip_id,
        Gossip.is_active == True
    ).first()
    
    if not gossip:
        return RedirectResponse(url="/gossip", status_code=303)
    
    # Increment view count
    gossip.view_count += 1
    db.commit()
    
    # Get related content
    related_content = None
    if gossip.related_content_id:
        related_content = db.query(Content).filter(
            Content.id == gossip.related_content_id
        ).first()
    
    # Get similar gossip (same tag or related content)
    similar_query = db.query(Gossip).filter(
        Gossip.is_active == True,
        Gossip.id != gossip_id
    )
    
    if gossip.related_content_id:
        similar_query = similar_query.filter(
            Gossip.related_content_id == gossip.related_content_id
        )
    else:
        similar_query = similar_query.filter(Gossip.tag == gossip.tag)
    
    similar_gossip = similar_query.order_by(Gossip.scraped_at.desc()).limit(3).all()
    
    return templates.TemplateResponse(
        "gossip/detail.html",
        {
            "request": request,
            "user": user,
            "gossip": gossip,
            "related_content": related_content,
            "similar_gossip": similar_gossip
        }
    )


@router.post("/refresh")
async def refresh_gossip(request: Request, db: Session = Depends(get_db)):
    """Manually trigger gossip refresh"""
    import asyncio
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    try:
        from app.agents.gossip_agent import gossip_agent
        
        # Get user's tracked content for personalized gossip
        from app.models import LibraryItem
        from app.models.library import WatchStatus
        
        tracked_titles = []
        library_items = db.query(LibraryItem).filter(
            LibraryItem.user_id == user.id,
            LibraryItem.status.in_([WatchStatus.WATCHING, WatchStatus.PLANNED])
        ).all()
        
        for item in library_items:
            if item.content:
                tracked_titles.append(item.content.title)
        
        # Run gossip scraper
        async def scrape():
            return await gossip_agent.scrape_gossip(tracked_titles[:10])
        
        results = await asyncio.wait_for(scrape(), timeout=30.0)
        
        logger.info(f"Gossip refresh completed: {len(results)} items")
        
    except asyncio.TimeoutError:
        logger.warning("Gossip refresh timeout")
    except Exception as e:
        logger.error(f"Error refreshing gossip: {e}")
    
    return RedirectResponse(url="/gossip", status_code=303)


@router.get("/content/{content_id}", response_class=HTMLResponse)
async def gossip_for_content(
    request: Request,
    content_id: int,
    db: Session = Depends(get_db)
):
    """Get all gossip related to a specific content"""
    from app.main import templates
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        return RedirectResponse(url="/gossip", status_code=303)
    
    gossip_items = db.query(Gossip).filter(
        Gossip.is_active == True,
        Gossip.related_content_id == content_id
    ).order_by(Gossip.scraped_at.desc()).all()
    
    return templates.TemplateResponse(
        "gossip/content.html",
        {
            "request": request,
            "user": user,
            "content": content,
            "gossip_items": gossip_items
        }
    )

