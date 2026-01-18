"""
Search & AI routes for content discovery
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


@router.get("", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: str = Query(None),
    db: Session = Depends(get_db)
):
    """Search & AI page"""
    from app.templates import templates
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    results = []
    ai_response = None
    is_searching = False
    
    if q:
        # First, search existing content in database
        search_term = f"%{q}%"
        results = db.query(Content).filter(
            Content.title.ilike(search_term) |
            Content.description.ilike(search_term)
        ).limit(20).all()
        
        # If no results, try AI-powered search
        if not results and settings.tavily_api_key:
            try:
                from tavily import TavilyClient
                tavily = TavilyClient(api_key=settings.tavily_api_key)
                
                # Search for content
                search_results = tavily.search(
                    query=f"{q} movie OR tv show",
                    search_depth="advanced",
                    max_results=10
                )
                
                # Process and create content entries
                for item in search_results.get('results', []):
                    # Try to extract content info from search results
                    title = extract_title_from_result(item, q)
                    if title:
                        # Check if content exists
                        existing = db.query(Content).filter(
                            Content.title.ilike(f"%{title}%")
                        ).first()
                        
                        if not existing:
                            # Create new content entry
                            content_type = guess_content_type(item.get('content', ''))
                            new_content = Content(
                                title=title,
                                content_type=content_type,
                                description=item.get('content', '')[:500]
                            )
                            db.add(new_content)
                            results.append(new_content)
                        else:
                            if existing not in results:
                                results.append(existing)
                
                db.commit()
                
                # If still no structured results, provide AI response
                if not results:
                    ai_response = format_ai_response(search_results)
                    
            except Exception as e:
                logger.error(f"Search error: {e}")
                ai_response = f"Unable to search at this time. Please try again later."
    
    return templates.TemplateResponse(
        "search.html",
        {
            "request": request,
            "user": user,
            "query": q,
            "results": results,
            "ai_response": ai_response,
            "is_searching": is_searching
        }
    )


@router.get("/api/search")
async def api_search(
    request: Request,
    q: str = Query(...),
    db: Session = Depends(get_db)
):
    """API endpoint for search suggestions"""
    user = get_current_user(request, db)
    if not user:
        return {"error": "Unauthorized"}
    
    search_term = f"%{q}%"
    results = db.query(Content).filter(
        Content.title.ilike(search_term)
    ).limit(10).all()
    
    return {
        "results": [
            {
                "id": c.id,
                "title": c.title,
                "type": c.content_type,
                "poster_url": c.poster_url
            }
            for c in results
        ]
    }


def extract_title_from_result(result: dict, query: str) -> str:
    """Extract a content title from search result"""
    title = result.get('title', '')
    
    # Clean up common patterns
    title = title.split(' - ')[0]
    title = title.split(' | ')[0]
    title = title.split(': ')[0] if ':' in title else title
    
    # If title seems like a news headline, try to extract the show/movie name
    keywords = ['season', 'episode', 'cast', 'release', 'premiere', 'trailer', 'review']
    for keyword in keywords:
        if keyword in title.lower():
            parts = title.lower().split(keyword)
            if parts[0].strip():
                title = parts[0].strip().title()
                break
    
    return title.strip()[:100] if title else None


def guess_content_type(text: str) -> str:
    """Guess if content is movie or TV show from text"""
    text_lower = text.lower()
    tv_keywords = ['season', 'episode', 'series', 'show', 'episodes', 'premiere', 'finale']
    movie_keywords = ['film', 'movie', 'theatrical', 'box office', 'cinema']
    
    tv_score = sum(1 for k in tv_keywords if k in text_lower)
    movie_score = sum(1 for k in movie_keywords if k in text_lower)
    
    return 'tv_show' if tv_score > movie_score else 'movie'


def format_ai_response(search_results: dict) -> str:
    """Format search results into a readable AI response"""
    if not search_results.get('results'):
        return "I couldn't find specific information about that. Try searching for a specific show or movie title."
    
    response_parts = []
    for result in search_results['results'][:5]:
        title = result.get('title', 'Unknown')
        content = result.get('content', '')[:200]
        url = result.get('url', '')
        
        response_parts.append(f"""
        <div class="mb-4 p-4 bg-white/5 rounded-lg">
            <h4 class="font-semibold text-sm mb-2">{title}</h4>
            <p class="text-sm text-muted-foreground mb-2">{content}...</p>
            <a href="{url}" target="_blank" class="text-xs text-primary hover:underline">Read more →</a>
        </div>
        """)
    
    return "".join(response_parts)

