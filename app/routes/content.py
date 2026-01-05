"""
Content routes for Movies and TV Shows - Web Scraping Based
Scrapes actual movie/TV show data from entertainment websites
"""
import logging
import asyncio
import re
from fastapi import APIRouter, Request, Depends, Query, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session
from datetime import datetime

from app.database import get_db
from app.models import User, Content, LibraryItem, WatchStatus
from app.routes.auth import get_current_user
from app.config import settings
from app.services.content_scraper import get_content_scraper

logger = logging.getLogger(__name__)
router = APIRouter()


def is_article_title(title: str) -> bool:
    """Check if title looks like an article rather than actual movie/show"""
    if not title:
        return True
    
    article_patterns = [
        r'\d{4}\s+movies',
        r'\d{4}\s*-\s*$',  # "Best Films of 2024-"
        r'best\s+(upcoming|new|films|movies|tv|of)',
        r'top\s+\d+',
        r'the\s+\d+\s+best',
        r'the\s+(ten|twenty|best|top)\s+(best|movies)',
        r'release\s+dates',
        r'ranked\s+by',
        r'updated\s+weekly',
        r'school\s+year',
        r'trailers?\s*\)',
        r'so\s+far',
        r'r/movies',
        r'r/television',
        r'winter\s+\d{4}',
        r'letterboxd',
        r'tomatometer',
        r'most\s+anticipated',
        r'new\s+and\s+upcoming',
        r'^\s*my\s+top\s+\d+',
        r'^\s*top\s+movies\s+of',
    ]
    
    title_lower = title.lower()
    for pattern in article_patterns:
        if re.search(pattern, title_lower):
            return True
    
    # Title too long (likely an article)
    if len(title) > 55:
        return True
    
    # Title is too short (might be garbage)
    if len(title) < 2:
        return True
    
    return False


async def save_scraped_content(db: Session, item: dict, content_type: str) -> Content:
    """Save scraped content to database"""
    title = item.get('title', '').strip()
    if not title or is_article_title(title):
        return None
    
    # Check if already exists (by title and type)
    existing = db.query(Content).filter(
        Content.title.ilike(f"%{title}%"),
        Content.content_type == content_type
    ).first()
    
    if existing:
        # Update with new data if we have more info
        if item.get('poster_url') and not existing.poster_url:
            existing.poster_url = item.get('poster_url')
        if item.get('rating') and not existing.rating:
            existing.rating = item.get('rating')
        if item.get('description') and not existing.description:
            existing.description = item.get('description')[:500] if item.get('description') else None
        existing.updated_at = datetime.utcnow()
        db.commit()
        return existing
    
    # Create new content
    content = Content(
        title=title[:200],
        content_type=content_type,
        description=item.get('description', '')[:500] if item.get('description') else None,
        poster_url=item.get('poster_url'),
        rating=item.get('rating'),
        imdb_id=item.get('imdb_id'),
        external_id=item.get('external_id'),
        release_date=item.get('release_date'),
    )
    
    db.add(content)
    db.commit()
    db.refresh(content)
    return content


async def fetch_missing_posters(db: Session, items: list, content_type: str):
    """Background task to fetch posters for items missing them"""
    scraper = get_content_scraper()
    
    for item in items:
        if not item.poster_url:
            try:
                poster = await scraper.get_poster_from_search(item.title, content_type)
                if poster:
                    item.poster_url = poster
                    db.commit()
            except Exception as e:
                logger.warning(f"Failed to fetch poster for {item.title}: {e}")


# ============= MOVIES =============

@router.get("/movies", response_class=HTMLResponse)
async def movies_page(
    request: Request,
    filter: str = Query("all"),
    db: Session = Depends(get_db)
):
    """Movies page"""
    from app.main import templates
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Query movies from our database
    query = db.query(Content).filter(Content.content_type == "movie")
    
    if filter == "trending":
        query = query.order_by(Content.rating.desc().nullslast())
    elif filter == "recent":
        query = query.order_by(Content.created_at.desc())
    else:
        query = query.order_by(Content.title)
    
    movies = query.limit(50).all()
    
    # Get user's library items for status display
    library_items = db.query(LibraryItem).filter(
        LibraryItem.user_id == user.id
    ).all()
    library_status = {item.content_id: item.status.value for item in library_items}
    
    return templates.TemplateResponse(
        "movies.html",
        {
            "request": request,
            "user": user,
            "movies": movies,
            "current_filter": filter,
            "library_status": library_status,
            "scraping_enabled": bool(settings.tavily_api_key or settings.gemini_api_key)
        }
    )


@router.post("/movies/refresh")
async def refresh_movies(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Discover new movies by scraping entertainment websites"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    scraper = get_content_scraper()
    preferences = user.preferred_genres or "popular"
    
    try:
        logger.info(f"Starting movie discovery for user preferences: {preferences}")
        
        # Scrape movies from various sources
        scraped_movies = await scraper.discover_movies(preferences=preferences, limit=30)
        
        saved_items = []
        for movie_data in scraped_movies:
            try:
                content = await save_scraped_content(db, movie_data, "movie")
                if content:
                    saved_items.append(content)
            except Exception as e:
                logger.warning(f"Failed to save movie {movie_data.get('title')}: {e}")
                continue
        
        logger.info(f"Discovered and saved {len(saved_items)} movies")
        
        # Fetch missing posters in background
        items_without_posters = [item for item in saved_items if not item.poster_url]
        if items_without_posters:
            background_tasks.add_task(fetch_missing_posters, db, items_without_posters, "movie")
        
    except Exception as e:
        logger.error(f"Error discovering movies: {e}")
    
    return RedirectResponse(url="/movies", status_code=303)


# ============= TV SHOWS =============

@router.get("/tv-shows", response_class=HTMLResponse)
async def tv_shows_page(
    request: Request,
    filter: str = Query("all"),
    db: Session = Depends(get_db)
):
    """TV Shows page"""
    from app.main import templates
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Query TV shows from our database
    query = db.query(Content).filter(Content.content_type == "tv_show")
    
    if filter == "trending":
        query = query.order_by(Content.rating.desc().nullslast())
    elif filter == "recent":
        query = query.order_by(Content.created_at.desc())
    else:
        query = query.order_by(Content.title)
    
    tv_shows = query.limit(50).all()
    
    # Get user's library items for status display
    library_items = db.query(LibraryItem).filter(
        LibraryItem.user_id == user.id
    ).all()
    library_status = {item.content_id: item.status.value for item in library_items}
    
    return templates.TemplateResponse(
        "tv_shows.html",
        {
            "request": request,
            "user": user,
            "tv_shows": tv_shows,
            "current_filter": filter,
            "library_status": library_status,
            "scraping_enabled": bool(settings.tavily_api_key or settings.gemini_api_key)
        }
    )


@router.post("/tv-shows/refresh")
async def refresh_tv_shows(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Discover new TV shows by scraping entertainment websites"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    scraper = get_content_scraper()
    preferences = user.preferred_genres or "popular"
    
    try:
        logger.info(f"Starting TV show discovery for user preferences: {preferences}")
        
        # Scrape TV shows from various sources
        scraped_shows = await scraper.discover_tv_shows(preferences=preferences, limit=30)
        
        saved_items = []
        for show_data in scraped_shows:
            try:
                content = await save_scraped_content(db, show_data, "tv_show")
                if content:
                    saved_items.append(content)
            except Exception as e:
                logger.warning(f"Failed to save TV show {show_data.get('title')}: {e}")
                continue
        
        logger.info(f"Discovered and saved {len(saved_items)} TV shows")
        
        # Fetch missing posters in background
        items_without_posters = [item for item in saved_items if not item.poster_url]
        if items_without_posters:
            background_tasks.add_task(fetch_missing_posters, db, items_without_posters, "tv_show")
        
    except Exception as e:
        logger.error(f"Error discovering TV shows: {e}")
    
    return RedirectResponse(url="/tv-shows", status_code=303)


# ============= CLEANUP =============

@router.post("/cleanup-articles")
async def cleanup_article_entries(
    request: Request,
    db: Session = Depends(get_db)
):
    """Remove article-style entries from the content database"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Get all content and filter out articles
    all_content = db.query(Content).all()
    deleted_count = 0
    
    for content in all_content:
        if is_article_title(content.title):
            # Check if any library items reference this
            library_refs = db.query(LibraryItem).filter(
                LibraryItem.content_id == content.id
            ).count()
            
            if library_refs == 0:
                db.delete(content)
                deleted_count += 1
    
    db.commit()
    logger.info(f"Cleaned up {deleted_count} article-style entries")
    
    # Redirect back to referring page
    referer = request.headers.get("referer", "/movies")
    return RedirectResponse(url=referer, status_code=303)


# ============= ADD TO LIBRARY =============

@router.post("/add-to-library")
async def add_to_library(
    request: Request,
    content_id: int = Form(...),
    status: str = Form("planned"),
    db: Session = Depends(get_db)
):
    """Add content to user's library with a specific status"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Map status string to enum
    status_map = {
        "watching": WatchStatus.WATCHING,
        "planned": WatchStatus.PLANNED,
        "completed": WatchStatus.COMPLETED,
        "dropped": WatchStatus.DROPPED,
        "maybe": WatchStatus.MAYBE
    }
    
    watch_status = status_map.get(status, WatchStatus.PLANNED)
    
    # Check if already in library
    existing = db.query(LibraryItem).filter(
        LibraryItem.user_id == user.id,
        LibraryItem.content_id == content_id
    ).first()
    
    if existing:
        # Update status
        existing.status = watch_status
        existing.updated_at = datetime.utcnow()
        db.commit()
    else:
        # Verify content exists
        content = db.query(Content).filter(Content.id == content_id).first()
        if content:
            library_item = LibraryItem(
                user_id=user.id,
                content_id=content_id,
                status=watch_status
            )
            db.add(library_item)
            db.commit()
    
    # Redirect back to referring page
    referer = request.headers.get("referer", "/movies")
    return RedirectResponse(url=referer, status_code=303)


# ============= CONTENT DETAIL =============

@router.get("/{content_id}", response_class=HTMLResponse)
async def content_detail(
    request: Request,
    content_id: int,
    db: Session = Depends(get_db)
):
    """Content detail page"""
    from app.main import templates
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    content = db.query(Content).filter(Content.id == content_id).first()
    if not content:
        return RedirectResponse(url="/movies", status_code=303)
    
    # Get library status
    library_item = db.query(LibraryItem).filter(
        LibraryItem.user_id == user.id,
        LibraryItem.content_id == content_id
    ).first()
    
    return templates.TemplateResponse(
        "content_detail.html",
        {
            "request": request,
            "user": user,
            "content": content,
            "library_item": library_item
        }
    )
