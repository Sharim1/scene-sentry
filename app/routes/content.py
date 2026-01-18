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
    """Check if title looks like an article/news headline rather than actual movie/show title"""
    if not title:
        return True
    
    title_lower = title.lower().strip()
    
    # List/ranking article patterns
    list_patterns = [
        r'\d{4}\s+movies',
        r'\d{4}\s*-\s*$',  # "Best Films of 2024-"
        r'best\s+(upcoming|new|films|movies|tv|shows?|of|series)',
        r'top\s+\d+',
        r'the\s+\d+\s+best',
        r'the\s+(ten|twenty|best|top)\s+(best|movies|shows)',
        r'^\d+\s+(best|top|new|great)',  # "10 Best Movies..."
        r'most\s+anticipated',
        r'new\s+and\s+upcoming',
        r'^\s*my\s+top\s+\d+',
        r'^\s*top\s+movies\s+of',
        r'ranked\s+by',
        r'updated\s+weekly',
        r'so\s+far',
        r'best\s+of\s+\d{4}',
        r'movies?\s+to\s+watch',
        r'shows?\s+to\s+watch',
        r'must[\s-]watch',
        r'what\s+to\s+watch',
        r'streaming\s+now',
        r'now\s+streaming',
        r'available\s+(now|on)',
        r'coming\s+soon',
        r'worth\s+watching',
    ]
    
    # News/article patterns
    news_patterns = [
        r'cancel+ed\s+(after|at|by)',
        r'renewed\s+(for|by)',
        r'announces?',
        r'announced',
        r'confirms?',
        r'confirmed',
        r'exclusive:',
        r'breaking:',
        r'report:',
        r'news:',
        r'update:',
        r'official:',
        r'first\s+look',
        r'sneak\s+peek',
        r'behind\s+the\s+scenes',
        r'interview',
        r'premiere\s+date',
        r'release\s+dates?',
        r'streaming\s+on',
        r'coming\s+to',
        r'watch\s+the\s+trailer',
        r'season\s+\d+\s+(premiere|finale|renewal|canceled)',
        r'gets\s+(renewed|cancelled|canceled)',
        r'will\s+(return|end|premiere)',
        r'picked\s+up',
        r'greenlit',
        r'ordered\s+to\s+series',
        r'adds\s+to\s+cast',
        r'joins\s+(cast|series)',
        r'set\s+to\s+star',
        r'lands\s+role',
        r'cast\s+in',
        r'wraps\s+filming',
        r'begins\s+production',
        r'box\s+office',
        r'opening\s+weekend',
        r'streaming\s+numbers',
        r'\bratings\b',
        r'viewership',
        r'review[s:]',
        r'recap',
        r'explained',
        r'ending\s+explained',
        r'spoilers?',
        r'everything\s+(you\s+)?know',
        r'everything\s+we\s+know',
        r'what\s+we\s+know',
        r'guide\s+to',
        r'how\s+to\s+watch',
        r'where\s+to\s+watch',
        r'when\s+(does|is|will)',
        r'who\s+(is|are|plays)',
    ]
    
    # Platform/website indicators
    platform_patterns = [
        r'r/movies',
        r'r/television',
        r'letterboxd',
        r'tomatometer',
        r'rotten\s+tomatoes',
        r'imdb\s+',
        r'metacritic',
        r'reddit',
        r'twitter|x\.com',
    ]
    
    # Date/time patterns often found in article titles
    date_patterns = [
        r'winter\s+\d{4}',
        r'summer\s+\d{4}',
        r'spring\s+\d{4}',
        r'fall\s+\d{4}',
        r'january|february|march|april|may|june|july|august|september|october|november|december',
        r'school\s+year',
        r'this\s+week',
        r'this\s+month',
        r'\d{1,2}/\d{1,2}/\d{2,4}',
    ]
    
    # Combine and check all patterns
    all_patterns = list_patterns + news_patterns + platform_patterns + date_patterns
    for pattern in all_patterns:
        if re.search(pattern, title_lower):
            return True
    
    # Title too long (likely an article headline)
    if len(title) > 60:
        return True
    
    # Title is too short (might be garbage)
    if len(title) < 2:
        return True
    
    # Contains quotes with extra text (usually news format: "'Show' Does Something")
    if title_lower.startswith("'") or title_lower.startswith('"'):
        # Find the closing quote
        quote_char = title[0]
        end_quote = title.find(quote_char, 1)
        if end_quote > 0 and end_quote < len(title) - 2:
            # There's text after the quoted title
            after_quote = title[end_quote + 1:].strip()
            if len(after_quote) > 3:  # Significant text after title
                return True
    
    # Contains common article verbiage
    article_words = [
        'here are', "here's", 'check out', 'see the', 'look at',
        'you need to', 'you should', 'we rank', 'we review',
        'our picks', 'our top', 'our favorite', 'editor',
    ]
    for word in article_words:
        if word in title_lower:
            return True
    
    # Contains trailer/video indicators (often not actual titles)
    if 'trailer' in title_lower and not title_lower.endswith('trailer'):
        # "Movie Name Trailer" is OK, "Watch the Trailer for Movie" is not
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
    q: str = Query(None),
    db: Session = Depends(get_db)
):
    """Movies page with search functionality"""
    from app.main import templates
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Query movies from our database
    query = db.query(Content).filter(Content.content_type == "movie")
    
    # Apply search filter if query provided
    search_query = q
    if q:
        query = query.filter(
            Content.title.ilike(f"%{q}%") |
            Content.description.ilike(f"%{q}%")
        )
    
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
            "search_query": search_query,
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
    """Discover new movies using background task system"""
    from app.services.task_manager import get_task_manager, TaskType
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    task_manager = get_task_manager()
    preferences = user.preferred_genres or "popular"
    
    # Check if user already has an active movie discovery task
    existing_tasks = await task_manager.get_user_tasks(user.id, active_only=True)
    for existing in existing_tasks:
        if existing.type == TaskType.MOVIE_DISCOVERY:
            logger.info(f"Movie discovery already running for user {user.id}")
            return RedirectResponse(url="/movies", status_code=303)
    
    # Create and run task
    task = await task_manager.create_task(
        task_type=TaskType.MOVIE_DISCOVERY,
        user_id=user.id,
        name="Discovering Movies"
    )
    
    async def run_movie_discovery(task, tm):
        scraper = get_content_scraper()
        
        await tm.update_task(task.id, progress=10, message="Fetching movie data...")
        
        try:
            scraped_movies = await scraper.discover_movies(preferences=preferences, limit=30)
            await tm.update_task(task.id, progress=40, message=f"Found {len(scraped_movies)} movies, saving...")
            
            saved_count = 0
            for i, movie_data in enumerate(scraped_movies):
                try:
                    with next(get_db()) as db_session:
                        content = await save_scraped_content(db_session, movie_data, "movie")
                        if content:
                            saved_count += 1
                except Exception as e:
                    logger.warning(f"Failed to save movie {movie_data.get('title')}: {e}")
                
                progress = 40 + int((i / max(len(scraped_movies), 1)) * 50)
                if i % 5 == 0:  # Update every 5 items
                    await tm.update_task(task.id, progress=progress, message=f"Saved {saved_count} movies...")
            
            return {"saved": saved_count, "total": len(scraped_movies)}
            
        except Exception as e:
            logger.error(f"Movie discovery error: {e}")
            raise
    
    background_tasks.add_task(task_manager.run_task, task.id, run_movie_discovery)
    logger.info(f"Started movie discovery task {task.id} for user {user.id}")
    
    return RedirectResponse(url="/movies", status_code=303)


# ============= TV SHOWS =============

@router.get("/tv-shows", response_class=HTMLResponse)
async def tv_shows_page(
    request: Request,
    filter: str = Query("all"),
    q: str = Query(None),
    db: Session = Depends(get_db)
):
    """TV Shows page with search functionality"""
    from app.main import templates
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Query TV shows from our database
    query = db.query(Content).filter(Content.content_type == "tv_show")
    
    # Apply search filter if query provided
    search_query = q
    if q:
        query = query.filter(
            Content.title.ilike(f"%{q}%") |
            Content.description.ilike(f"%{q}%")
        )
    
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
            "search_query": search_query,
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
    """Discover new TV shows using background task system"""
    from app.services.task_manager import get_task_manager, TaskType
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    task_manager = get_task_manager()
    preferences = user.preferred_genres or "popular"
    
    # Check if user already has an active TV discovery task
    existing_tasks = await task_manager.get_user_tasks(user.id, active_only=True)
    for existing in existing_tasks:
        if existing.type == TaskType.TV_DISCOVERY:
            logger.info(f"TV discovery already running for user {user.id}")
            return RedirectResponse(url="/tv-shows", status_code=303)
    
    # Create and run task
    task = await task_manager.create_task(
        task_type=TaskType.TV_DISCOVERY,
        user_id=user.id,
        name="Discovering TV Shows"
    )
    
    async def run_tv_discovery(task, tm):
        scraper = get_content_scraper()
        
        await tm.update_task(task.id, progress=10, message="Fetching TV show data...")
        
        try:
            scraped_shows = await scraper.discover_tv_shows(preferences=preferences, limit=30)
            await tm.update_task(task.id, progress=40, message=f"Found {len(scraped_shows)} TV shows, saving...")
            
            saved_count = 0
            for i, show_data in enumerate(scraped_shows):
                try:
                    with next(get_db()) as db_session:
                        content = await save_scraped_content(db_session, show_data, "tv_show")
                        if content:
                            saved_count += 1
                except Exception as e:
                    logger.warning(f"Failed to save TV show {show_data.get('title')}: {e}")
                
                progress = 40 + int((i / max(len(scraped_shows), 1)) * 50)
                if i % 5 == 0:  # Update every 5 items
                    await tm.update_task(task.id, progress=progress, message=f"Saved {saved_count} TV shows...")
            
            return {"saved": saved_count, "total": len(scraped_shows)}
            
        except Exception as e:
            logger.error(f"TV discovery error: {e}")
            raise
    
    background_tasks.add_task(task_manager.run_task, task.id, run_tv_discovery)
    logger.info(f"Started TV discovery task {task.id} for user {user.id}")
    
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
