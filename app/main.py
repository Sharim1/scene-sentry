"""
FastAPI Application Entry Point
"""
import logging
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from starlette.middleware.sessions import SessionMiddleware

from starlette.exceptions import HTTPException as StarletteHTTPException

from app.config import settings
from app.database import get_db, init_db
from app.models.user import User
from app.templates import templates, static_path

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Reduce SQLAlchemy engine noise (removes ROLLBACK/COMMIT logs)
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    logger.info(f"Environment: {settings.env}")
    logger.info(f"Clerk authentication: {'enabled' if settings.is_clerk_configured else 'disabled'}")

    init_db(drop_all=False)
    logger.info("Database initialized")

    from app.tasks.scheduler import start_scheduler

    start_scheduler()
    logger.info("Background scheduler started")

    yield

    from app.tasks.scheduler import shutdown_scheduler

    shutdown_scheduler()
    logger.info("Application shutdown complete")


# Create FastAPI app
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-powered cinema intelligence platform",
    lifespan=lifespan,
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
    https_only=settings.env == "production",
)

# Mount static files
app.mount("/static", StaticFiles(directory=static_path), name="static")


class HealthResponse(BaseModel):
    status: str
    version: str
    clerk_configured: bool


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
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
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
def health_check() -> HealthResponse:
    """Health check endpoint"""
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        clerk_configured=settings.is_clerk_configured,
    )


@app.get("/favicon.ico")
def favicon():
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
from app.routes import (
    api,
    auth,
    contact,
    content,
    dashboard,
    gossip,
    library,
    notifications,
    reminders,
    search_page,
)

app.include_router(contact.router)
app.include_router(auth.router)
app.include_router(dashboard.router)
app.include_router(library.router)
app.include_router(gossip.router)
app.include_router(api.router)
app.include_router(notifications.router)
app.include_router(reminders.router)
app.include_router(search_page.router)
app.include_router(content.router)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle HTTP exceptions with custom error pages"""
    if exc.status_code == 404:
        return templates.TemplateResponse(
            "errors/404.html",
            {"request": request},
            status_code=404,
        )
    if exc.status_code == 429:
        return templates.TemplateResponse(
            "errors/error.html",
            {
                "request": request,
                "error": "Too many requests. Please slow down and try again.",
                "status_code": 429,
            },
            status_code=429,
        )
    return templates.TemplateResponse(
        "errors/error.html",
        {"request": request, "error": str(exc.detail), "status_code": exc.status_code},
        status_code=exc.status_code,
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions"""
    logger.error(f"Unhandled exception: {exc}")
    logger.error(traceback.format_exc())

    error_message = str(exc) if settings.debug else "An unexpected error occurred"

    return templates.TemplateResponse(
        "errors/error.html",
        {"request": request, "error": error_message, "status_code": 500},
        status_code=500,
    )
