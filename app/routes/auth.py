"""
Authentication routes with Clerk integration

Security features:
- Webhook signature verification using Svix
- Rate limiting on auth endpoints
- Proper session handling
"""
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Request, Response, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.database import get_db
from app.models.user import User
from app.config import settings
from app.templates import templates

logger = logging.getLogger(__name__)
router = APIRouter()

# Rate limiter instance
limiter = Limiter(key_func=get_remote_address)


# Auth helpers - supports both Clerk and session-based auth
def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """
    Get current user from Clerk middleware or session fallback.
    
    Priority:
    1. Clerk authentication (if configured)
    2. Session-based authentication (fallback for dev/non-Clerk setups)
    """
    # Primary: Check if Clerk middleware identified a user
    clerk_user_id = getattr(request.state, "clerk_user_id", None)
    if clerk_user_id:
        user = db.query(User).filter(User.id == clerk_user_id).first()
        if user:
            request.state.user = user
            return user
    
    # Fallback: Session-based auth (only if Clerk is not configured)
    if not settings.is_clerk_configured:
        session_user_id = getattr(request.state, "session_user_id", None)
        if session_user_id:
            user = db.query(User).filter(User.id == session_user_id).first()
            if user:
                request.state.user = user
                return user
        
        # Direct session check
        if hasattr(request, "session"):
            user_id = request.session.get("user_id")
            if user_id:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    request.state.user = user
                    return user
    
    return None


def require_auth(request: Request, db: Session = Depends(get_db)) -> User:
    """Require authenticated user - raises 401 if not authenticated"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@router.get("/login", response_class=HTMLResponse, name="login")
async def login_page(request: Request):
    """Login page - shows Clerk SignIn or traditional form"""
    clerk_user_id = getattr(request.state, "clerk_user_id", None)
    session_user_id = getattr(request.state, "session_user_id", None)
    if clerk_user_id or session_user_id:
        return RedirectResponse(url="/dashboard", status_code=303)
    
    fallback = request.query_params.get("fallback") == "1"
    clerk_enabled = settings.is_clerk_configured and not fallback
    
    return templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "error": None,
            "clerk_enabled": clerk_enabled,
            "clerk_publishable_key": settings.clerk_publishable_key or "",
            "clear_clerk_session": False
        }
    )


@router.post("/login")
@limiter.limit(settings.rate_limit_auth)
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """
    Process login (fallback when Clerk not configured).
    Rate limited to prevent brute force attacks.
    """
    user = db.query(User).filter(User.username == username).first()
    
    if user and user.check_password(password):
        # Set session
        request.session["user_id"] = user.id
        request.session["username"] = user.username
        
        # Update last login
        user.last_login = datetime.now(timezone.utc)
        db.commit()
        
        logger.info(f"User logged in: {user.username}")
        return RedirectResponse(url="/dashboard", status_code=303)
    
    logger.warning(f"Failed login attempt for username: {username}")
    return templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "error": "Invalid username or password",
            "clerk_enabled": settings.is_clerk_configured,
            "clerk_publishable_key": settings.clerk_publishable_key or "",
        },
        status_code=400
    )


@router.get("/register", response_class=HTMLResponse, name="register")
async def register_page(request: Request):
    """Registration page - shows Clerk SignUp or traditional form"""
    clerk_user_id = getattr(request.state, "clerk_user_id", None)
    session_user_id = getattr(request.state, "session_user_id", None)
    if clerk_user_id or session_user_id:
        return RedirectResponse(url="/dashboard", status_code=303)
    
    fallback = request.query_params.get("fallback") == "1"
    clerk_enabled = settings.is_clerk_configured and not fallback
    
    return templates.TemplateResponse(
        "auth/register.html",
        {
            "request": request,
            "error": None,
            "clerk_enabled": clerk_enabled,
            "clerk_publishable_key": settings.clerk_publishable_key or "",
            "clear_clerk_session": False
        }
    )


@router.post("/register")
@limiter.limit(settings.rate_limit_auth)
async def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    search_api: str = Form("tavily"),
    db: Session = Depends(get_db)
):
    """
    Process registration (fallback when Clerk not configured).
    Rate limited to prevent abuse.
    """
    # Validate input length
    if len(username) < 3 or len(username) > 80:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Username must be between 3 and 80 characters"},
            status_code=400
        )
    
    if len(password) < 8:
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Password must be at least 8 characters"},
            status_code=400
        )
    
    # Check if user exists
    if db.query(User).filter(User.username == username).first():
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Username already exists"},
            status_code=400
        )
    
    if db.query(User).filter(User.email == email).first():
        return templates.TemplateResponse(
            "auth/register.html",
            {"request": request, "error": "Email already exists"},
            status_code=400
        )
    
    # Create user
    user = User(
        username=username,
        email=email,
        search_api_preference=search_api
    )
    user.set_password(password)
    
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Set session
    request.session["user_id"] = user.id
    request.session["username"] = user.username
    
    logger.info(f"New user registered: {user.username}")
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/logout", name="logout")
async def logout(request: Request):
    """
    Logout user - clears session and Clerk cookies.
    
    Note: For complete Clerk logout, the frontend should call Clerk.signOut()
    which will invalidate the session on Clerk's servers.
    """
    # Clear server-side session
    request.session.clear()
    
    response = RedirectResponse(url="/", status_code=303)
    
    # Clear Clerk cookies (client-side tokens)
    # Note: This doesn't invalidate the session on Clerk's servers,
    # but the tokens are short-lived (~60s) and will expire naturally
    response.delete_cookie("__session", path="/")
    response.delete_cookie("__clerk_db_jwt", path="/")
    response.delete_cookie("moviemind_session", path="/")
    
    # Clear any other auth-related cookies
    response.delete_cookie("__client_uat", path="/")
    
    logger.info("User logged out")
    return response


@router.post("/webhooks/clerk")
async def clerk_webhook(request: Request, db: Session = Depends(get_db)):
    """
    Handle Clerk webhook events with proper signature verification.
    
    Verifies webhook signature using Svix library to prevent spoofed events.
    Handles user lifecycle events: created, updated, deleted.
    """
    from svix.webhooks import Webhook, WebhookVerificationError
    
    if not settings.clerk_webhook_secret:
        logger.error("Clerk webhook secret not configured")
        raise HTTPException(status_code=500, detail="Webhook not configured")
    
    # Extract Svix headers for verification
    headers = {
        "svix-id": request.headers.get("svix-id", ""),
        "svix-timestamp": request.headers.get("svix-timestamp", ""),
        "svix-signature": request.headers.get("svix-signature", ""),
    }
    
    # Validate required headers are present
    if not all(headers.values()):
        logger.warning("Missing Svix headers in webhook request")
        raise HTTPException(status_code=400, detail="Missing webhook headers")
    
    # Get raw body for signature verification
    body = await request.body()
    
    # Verify webhook signature
    try:
        wh = Webhook(settings.clerk_webhook_secret)
        event = wh.verify(body, headers)
    except WebhookVerificationError as e:
        logger.warning(f"Webhook signature verification failed: {e}")
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    except Exception as e:
        logger.error(f"Webhook verification error: {e}")
        raise HTTPException(status_code=400, detail="Webhook verification failed")
    
    # Process verified event
    event_type = event.get("type")
    data = event.get("data", {})
    webhook_id = headers.get("svix-id", "unknown")
    
    logger.info(f"Processing Clerk webhook: {event_type} (id: {webhook_id})")
    
    try:
        if event_type == "user.created":
            await _handle_user_created(db, data)
        elif event_type == "user.updated":
            await _handle_user_updated(db, data)
        elif event_type == "user.deleted":
            await _handle_user_deleted(db, data)
        else:
            logger.debug(f"Unhandled webhook event type: {event_type}")
        
        return {"status": "ok", "event": event_type}
        
    except Exception as e:
        logger.error(f"Error processing webhook {event_type}: {e}")
        # Return 200 to prevent retries for processing errors
        # (signature was valid, just processing failed)
        return {"status": "error", "message": str(e)}


async def _handle_user_created(db: Session, data: dict):
    """Handle user.created webhook event"""
    clerk_id = data.get("id")
    if not clerk_id:
        logger.warning("user.created webhook missing user id")
        return
    
    # Check if user already exists (might have been created via JWT sync)
    existing_user = db.query(User).filter(User.clerk_id == clerk_id).first()
    if existing_user:
        logger.info(f"User {clerk_id} already exists, skipping creation")
        return
    
    # Extract user info
    email_addresses = data.get("email_addresses", [])
    primary_email = None
    for email_obj in email_addresses:
        if email_obj.get("id") == data.get("primary_email_address_id"):
            primary_email = email_obj.get("email_address")
            break
    if not primary_email and email_addresses:
        primary_email = email_addresses[0].get("email_address", "")
    
    username = data.get("username") or (primary_email.split("@")[0] if primary_email else f"user_{clerk_id[:8]}")
    
    # Ensure unique username
    base_username = username
    counter = 1
    while db.query(User).filter(User.username == username).first():
        username = f"{base_username}_{counter}"
        counter += 1
    
    user = User(
        clerk_id=clerk_id,
        username=username,
        email=primary_email or f"{clerk_id}@clerk.user",
        avatar_url=data.get("image_url")
    )
    db.add(user)
    db.commit()
    logger.info(f"Created user from webhook: {user.username} (clerk_id: {clerk_id[:8]}...)")


async def _handle_user_updated(db: Session, data: dict):
    """Handle user.updated webhook event"""
    clerk_id = data.get("id")
    if not clerk_id:
        return
    
    user = db.query(User).filter(User.clerk_id == clerk_id).first()
    if not user:
        logger.warning(f"user.updated webhook for unknown user: {clerk_id[:8]}...")
        return
    
    # Update email if changed
    email_addresses = data.get("email_addresses", [])
    for email_obj in email_addresses:
        if email_obj.get("id") == data.get("primary_email_address_id"):
            user.email = email_obj.get("email_address", user.email)
            break
    
    # Update avatar if changed
    if data.get("image_url"):
        user.avatar_url = data.get("image_url")
    
    db.commit()
    logger.info(f"Updated user from webhook: {user.username}")


async def _handle_user_deleted(db: Session, data: dict):
    """Handle user.deleted webhook event"""
    clerk_id = data.get("id")
    if not clerk_id:
        return
    
    user = db.query(User).filter(User.clerk_id == clerk_id).first()
    if user:
        username = user.username
        db.delete(user)
        db.commit()
        logger.info(f"Deleted user from webhook: {username} (clerk_id: {clerk_id[:8]}...)")
    else:
        logger.warning(f"user.deleted webhook for unknown user: {clerk_id[:8]}...")


@router.get("/settings", response_class=HTMLResponse, name="settings")
async def settings_page(
    request: Request,
    db: Session = Depends(get_db)
):
    """User settings page"""
    import json
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Parse current preferences
    current_genres = []
    if user.preferred_genres:
        try:
            current_genres = json.loads(user.preferred_genres)
        except (json.JSONDecodeError, TypeError):
            current_genres = []
    
    available_genres = [
        'Action', 'Adventure', 'Animation', 'Comedy', 'Crime', 'Documentary',
        'Drama', 'Family', 'Fantasy', 'History', 'Horror', 'Music', 'Mystery',
        'Romance', 'Science Fiction', 'Thriller', 'War', 'Western'
    ]
    
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "current_genres": current_genres,
            "available_genres": available_genres
        }
    )


@router.post("/settings")
async def update_settings(
    request: Request,
    search_api: str = Form("tavily"),
    discovery_frequency: int = Form(30),
    db: Session = Depends(get_db)
):
    """Update user settings"""
    import json
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Get form data
    form_data = await request.form()
    genres = form_data.getlist("genres")
    
    # Update user
    user.search_api_preference = search_api
    user.preferred_genres = json.dumps(genres)
    user.discovery_frequency = discovery_frequency
    
    db.commit()
    
    return RedirectResponse(url="/settings", status_code=303)
