"""
FastAPI Application Entry Point
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware
from typing import List, Tuple

from app.config import settings
from app.database import init_db

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Reduce SQLAlchemy engine noise (removes ROLLBACK/COMMIT logs)
logging.getLogger('sqlalchemy.engine').setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    # Initialize database tables (create if not exist)
    init_db(drop_all=False)
    logger.info("Database initialized")
    
    # Start background task scheduler
    from app.tasks.scheduler import start_scheduler
    start_scheduler()
    logger.info("Background scheduler started")
    
    yield
    
    # Shutdown
    from app.tasks.scheduler import shutdown_scheduler
    shutdown_scheduler()
    logger.info("Application shutdown complete")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered entertainment discovery and gossip platform",
    lifespan=lifespan
)

# Add Clerk authentication middleware first so it wraps session middleware
# Middleware order: Request -> ClerkAuth -> Session -> Route
# (middleware added last executes first)
from app.middleware.clerk import ClerkAuthMiddleware
app.add_middleware(ClerkAuthMiddleware)

# Add session middleware after Clerk so session is available when Clerk middleware runs
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="moviemind_session",
    max_age=86400 * 7,  # 7 days
    same_site="lax",
    https_only=False  # Set to True in production with HTTPS
)

# Mount static files
static_path = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=static_path), name="static")

# Setup Jinja2 templates
templates_path = Path(__file__).parent.parent / "templates"
templates = Jinja2Templates(directory=templates_path)

# Add custom template filters and globals
import os
import json

def from_json_filter(value):
    """Parse JSON string to Python object"""
    try:
        return json.loads(value) if value else []
    except:
        return []

def static_url(filename: str) -> str:
    """Generate static file URL for templates"""
    return f"/static/{filename}"

# Flash message storage (request-scoped via context var)
from contextvars import ContextVar
_flash_messages: ContextVar[List[Tuple[str, str]]] = ContextVar('flash_messages', default=[])


def flash(message: str, category: str = "info"):
    """Add a flash message to be displayed on next page load"""
    messages = _flash_messages.get()
    messages.append((category, message))
    _flash_messages.set(messages)


def get_flashed_messages(with_categories: bool = False):
    """Get and clear flash messages"""
    messages = _flash_messages.get()
    _flash_messages.set([])
    if with_categories:
        return messages
    return [msg for _, msg in messages]

def get_ai_status():
    """Get the current AI agent status based on configuration"""
    # Use settings which loads from .env file
    tavily_key = settings.tavily_api_key
    gemini_key = settings.gemini_api_key
    
    if not tavily_key:
        return {
            "status": "inactive",
            "message": "Tavily API key not configured",
            "details": "Add TAVILY_API_KEY to .env to enable gossip scraping",
            "color": "yellow"
        }
    
    if not gemini_key:
        return {
            "status": "limited",
            "message": "Gossip scraping enabled",
            "details": "Add GEMINI_API_KEY for AI-powered analysis",
            "color": "blue"
        }
    
    return {
        "status": "active",
        "message": "AI agents fully operational",
        "details": "Scraping variety.com, deadline.com...",
        "color": "green"
    }

templates.env.filters["from_json"] = from_json_filter
templates.env.globals["static_url"] = static_url
templates.env.globals["get_flashed_messages"] = get_flashed_messages
templates.env.globals["get_ai_status"] = get_ai_status
templates.env.globals["flash"] = flash

# Clerk configuration for frontend
templates.env.globals["clerk_publishable_key"] = settings.clerk_publishable_key or ""
templates.env.globals["clerk_enabled"] = bool(settings.clerk_publishable_key and settings.clerk_issuer)


# Include routers
from app.routes import auth, dashboard, library, gossip, api, search, content

app.include_router(auth.router, tags=["auth"])
app.include_router(dashboard.router, tags=["dashboard"])
app.include_router(library.router, prefix="/library", tags=["library"])
app.include_router(gossip.router, prefix="/gossip", tags=["gossip"])
app.include_router(api.router, prefix="/api", tags=["api"])
app.include_router(search.router, prefix="/search", tags=["search"])
app.include_router(content.router, tags=["content"])


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Landing page"""
    from app.routes.auth import get_current_user
    from app.database import get_db
    
    # Get user from middleware-set user_id (avoids detached session issues)
    user = None
    clerk_user_id = getattr(request.state, "clerk_user_id", None)
    session_user_id = getattr(request.state, "session_user_id", None)
    
    if clerk_user_id or session_user_id:
        db = next(get_db())
        try:
            from app.models.user import User
            user_id = clerk_user_id or session_user_id
            user = db.query(User).filter(User.id == user_id).first()
        finally:
            db.close()
    
    if user:
        return templates.TemplateResponse(
            "dashboard.html",
            {"request": request, "user": user}
        )
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "version": settings.app_version}


@app.get("/favicon.ico")
async def favicon():
    """Serve favicon or return 204 No Content if not available"""
    from fastapi.responses import FileResponse, Response
    
    # Check if favicon exists in static folder
    favicon_path = static_path / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(favicon_path)
    
    # Check for PNG favicon
    favicon_png_path = static_path / "images" / "favicon.png"
    if favicon_png_path.exists():
        return FileResponse(favicon_png_path, media_type="image/png")
    
    # Return 204 No Content to prevent repeated requests
    return Response(status_code=204)


# Error handlers
from fastapi.exceptions import HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException
import traceback


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions with custom error pages"""
    if exc.status_code == 404:
        return templates.TemplateResponse(
            "errors/404.html",
            {"request": request},
            status_code=404
        )
    return templates.TemplateResponse(
        "errors/error.html",
        {"request": request, "error": str(exc.detail), "status_code": exc.status_code},
        status_code=exc.status_code
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions"""
    # Log the full traceback
    logger.error(f"Unhandled exception: {exc}")
    logger.error(traceback.format_exc())
    
    return templates.TemplateResponse(
        "errors/error.html",
        {"request": request, "error": str(exc), "status_code": 500},
        status_code=500
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=5000,
        reload=settings.debug
    )

