"""
FastAPI Application Entry Point
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from pathlib import Path
from starlette.middleware.sessions import SessionMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.database import init_db, get_db
from app.models.user import User
from app.templates import templates, static_path, flash, get_flashed_messages

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
    logger.info(f"Environment: {settings.env}")
    logger.info(f"Clerk authentication: {'enabled' if settings.is_clerk_configured else 'disabled'}")
    
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
    description="AI-powered cinema intelligence platform",
    lifespan=lifespan
)

# Configure rate limiter
from app.routes.auth import limiter
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Add Clerk authentication middleware first so it wraps session middleware
# Middleware order: Request -> ClerkAuth -> Session -> Route
# (middleware added last executes first)
from app.middleware.clerk import ClerkAuthMiddleware
app.add_middleware(ClerkAuthMiddleware)

# Add session middleware after Clerk so session is available when Clerk middleware runs
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret or settings.secret_key,
    session_cookie="scenesentry_session",
    max_age=86400 * 7,  # 7 days
    same_site="lax",
    https_only=settings.env == "production"
)

# Mount static files
app.mount("/static", StaticFiles(directory=static_path), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Landing page"""
    user = None
    clerk_user_id = getattr(request.state, "clerk_user_id", None)
    session_user_id = getattr(request.state, "session_user_id", None)
    
    if clerk_user_id or session_user_id:
        db = next(get_db())
        try:
            user_id = clerk_user_id or session_user_id
            user = db.query(User).filter(User.id == user_id).first()
        finally:
            db.close()
    
    if user:
        return RedirectResponse(url="/dashboard", status_code=303)
    return templates.TemplateResponse(
        "index.html",
        {"request": request}
    )


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "version": settings.app_version,
        "clerk_configured": settings.is_clerk_configured
    }


@app.get("/favicon.ico")
async def favicon():
    """Serve favicon or return 204 No Content if not available"""
    from fastapi.responses import FileResponse, Response
    
    favicon_path = static_path / "favicon.ico"
    if favicon_path.exists():
        return FileResponse(favicon_path)
    
    favicon_png_path = static_path / "images" / "favicon.png"
    if favicon_png_path.exists():
        return FileResponse(favicon_png_path, media_type="image/png")
    
    return Response(status_code=204)


# Include routers -- content router last since it has a catch-all /{content_id} route
from app.routes import auth, dashboard, library, gossip, api, content, reminders, notifications, search_page, contact


app.include_router(contact.router, tags=["pages"])
app.include_router(auth.router, tags=["auth"])
app.include_router(dashboard.router, tags=["dashboard"])
app.include_router(library.router, prefix="/library", tags=["library"])
app.include_router(gossip.router, prefix="/gossip", tags=["gossip"])
app.include_router(api.router, prefix="/api", tags=["api"])
app.include_router(notifications.router, prefix="/api", tags=["notifications"])
app.include_router(reminders.router, prefix="/reminders", tags=["reminders"])
app.include_router(search_page.router, tags=["search"])
app.include_router(content.router, tags=["content"])


# Error handlers
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
    if exc.status_code == 429:
        return templates.TemplateResponse(
            "errors/error.html",
            {
                "request": request,
                "error": "Too many requests. Please slow down and try again.",
                "status_code": 429
            },
            status_code=429
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
    
    # Don't expose internal errors in production
    error_message = str(exc) if settings.debug else "An unexpected error occurred"
    
    return templates.TemplateResponse(
        "errors/error.html",
        {"request": request, "error": error_message, "status_code": 500},
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
