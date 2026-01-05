"""
Content routes for Movies and TV Shows
"""
import logging
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, Content
from app.routes.auth import get_current_user
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


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
    
    # Query movies
    query = db.query(Content).filter(Content.content_type == "movie")
    
    if filter == "trending":
        # Sort by rating/popularity
        query = query.order_by(Content.rating.desc().nullslast())
    elif filter == "recent":
        query = query.order_by(Content.created_at.desc())
    else:
        query = query.order_by(Content.title)
    
    movies = query.limit(50).all()
    
    return templates.TemplateResponse(
        "movies.html",
        {
            "request": request,
            "user": user,
            "movies": movies,
            "current_filter": filter
        }
    )


@router.post("/movies/refresh")
async def refresh_movies(
    request: Request,
    db: Session = Depends(get_db)
):
    """Discover new movies using AI"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    if settings.tavily_api_key:
        try:
            from tavily import TavilyClient
            tavily = TavilyClient(api_key=settings.tavily_api_key)
            
            # Get user preferences for personalized search
            preferences = user.preferred_genres or "popular"
            
            # Search for trending movies
            search_results = tavily.search(
                query=f"best {preferences} movies 2024 2025 upcoming releases",
                search_depth="advanced",
                max_results=15
            )
            
            # Process results
            for result in search_results.get('results', []):
                title = extract_movie_title(result)
                if title:
                    # Check if already exists
                    existing = db.query(Content).filter(
                        Content.title.ilike(f"%{title}%"),
                        Content.content_type == "movie"
                    ).first()
                    
                    if not existing:
                        content = Content(
                            title=title,
                            content_type="movie",
                            description=result.get('content', '')[:500]
                        )
                        db.add(content)
            
            db.commit()
            logger.info("Movies refreshed successfully")
            
        except Exception as e:
            logger.error(f"Error refreshing movies: {e}")
    
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
    
    # Query TV shows
    query = db.query(Content).filter(Content.content_type == "tv_show")
    
    if filter == "trending":
        query = query.order_by(Content.rating.desc().nullslast())
    elif filter == "recent":
        query = query.order_by(Content.created_at.desc())
    else:
        query = query.order_by(Content.title)
    
    tv_shows = query.limit(50).all()
    
    return templates.TemplateResponse(
        "tv_shows.html",
        {
            "request": request,
            "user": user,
            "tv_shows": tv_shows,
            "current_filter": filter
        }
    )


@router.post("/tv-shows/refresh")
async def refresh_tv_shows(
    request: Request,
    db: Session = Depends(get_db)
):
    """Discover new TV shows using AI"""
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    if settings.tavily_api_key:
        try:
            from tavily import TavilyClient
            tavily = TavilyClient(api_key=settings.tavily_api_key)
            
            # Get user preferences
            preferences = user.preferred_genres or "popular"
            
            # Search for trending TV shows
            search_results = tavily.search(
                query=f"best {preferences} TV shows series 2024 2025 new seasons",
                search_depth="advanced",
                max_results=15
            )
            
            # Process results
            for result in search_results.get('results', []):
                title = extract_tv_title(result)
                if title:
                    existing = db.query(Content).filter(
                        Content.title.ilike(f"%{title}%"),
                        Content.content_type == "tv_show"
                    ).first()
                    
                    if not existing:
                        content = Content(
                            title=title,
                            content_type="tv_show",
                            description=result.get('content', '')[:500]
                        )
                        db.add(content)
            
            db.commit()
            logger.info("TV shows refreshed successfully")
            
        except Exception as e:
            logger.error(f"Error refreshing TV shows: {e}")
    
    return RedirectResponse(url="/tv-shows", status_code=303)


def extract_movie_title(result: dict) -> str:
    """Extract movie title from search result"""
    title = result.get('title', '')
    content = result.get('content', '')
    
    # Clean common patterns
    title = title.split(' - ')[0]
    title = title.split(' | ')[0]
    title = title.split(': Review')[0]
    title = title.split(': Trailer')[0]
    
    # Remove year patterns
    import re
    title = re.sub(r'\s*\(\d{4}\)\s*$', '', title)
    title = re.sub(r'\s*\d{4}\s*$', '', title)
    
    return title.strip()[:100] if title and len(title) > 2 else None


def extract_tv_title(result: dict) -> str:
    """Extract TV show title from search result"""
    title = result.get('title', '')
    
    # Clean common patterns
    title = title.split(' - ')[0]
    title = title.split(' | ')[0]
    title = title.split(': Season')[0]
    title = title.split(' Season')[0]
    title = title.split(': Episode')[0]
    title = title.split(': Review')[0]
    
    # Remove quotes
    title = title.strip('"\'')
    
    import re
    title = re.sub(r'\s*\(\d{4}\)\s*$', '', title)
    
    return title.strip()[:100] if title and len(title) > 2 else None

