"""
Authentication routes with Clerk integration
"""
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, Response, Depends, HTTPException, Form
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()


# Auth helpers - supports both Clerk and session-based auth
def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Get current user from Clerk middleware or session fallback"""
    # Check if Clerk middleware identified a user (stored as user_id to avoid detached session issues)
    clerk_user_id = getattr(request.state, "clerk_user_id", None)
    if clerk_user_id:
        user = db.query(User).filter(User.id == clerk_user_id).first()
        if user:
            # Also store the user object for this request's lifetime
            request.state.user = user
            return user
    
    # Check session-based auth from middleware
    session_user_id = getattr(request.state, "session_user_id", None)
    if session_user_id:
        user = db.query(User).filter(User.id == session_user_id).first()
        if user:
            request.state.user = user
            return user
    
    # Fallback to session-based auth (direct check)
    if hasattr(request, "session"):
        user_id = request.session.get("user_id")
        if user_id:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                request.state.user = user
                return user
    
    return None


def require_auth(request: Request, db: Session = Depends(get_db)) -> User:
    """Require authenticated user"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@router.get("/login", response_class=HTMLResponse, name="login")
async def login_page(request: Request):
    """Login page - shows Clerk SignIn or traditional form"""
    from app.main import templates
    
    # Check if already logged in (check for user_id set by middleware)
    clerk_user_id = getattr(request.state, "clerk_user_id", None)
    session_user_id = getattr(request.state, "session_user_id", None)
    if clerk_user_id or session_user_id:
        return RedirectResponse(url="/dashboard", status_code=303)
    
    # Check if Clerk is enabled
    clerk_enabled = bool(settings.clerk_publishable_key and settings.clerk_issuer)
    
    # NOTE: We no longer clear Clerk cookies server-side.
    # Clerk's frontend SDK handles session management and refresh.
    # Clearing cookies here was causing issues with the handshake flow
    # where valid sessions were being invalidated prematurely.
    
    response = templates.TemplateResponse(
        "auth/login.html",
        {
            "request": request,
            "error": None,
            "clerk_enabled": clerk_enabled,
            "clerk_publishable_key": settings.clerk_publishable_key or "",
            "clear_clerk_session": False  # Let Clerk SDK handle session management
        }
    )
    
    return response


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Process login (fallback when Clerk not configured)"""
    from app.main import templates
    
    user = db.query(User).filter(User.username == username).first()
    
    if user and user.check_password(password):
        # Set session
        request.session["user_id"] = user.id
        request.session["username"] = user.username
        
        # Update last login
        user.last_login = datetime.utcnow()
        db.commit()
        
        return RedirectResponse(url="/dashboard", status_code=303)
    
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "error": "Invalid username or password"},
        status_code=400
    )


@router.get("/register", response_class=HTMLResponse, name="register")
async def register_page(request: Request):
    """Registration page - shows Clerk SignUp or traditional form"""
    from app.main import templates
    
    # Check if already logged in (check for user_id set by middleware)
    clerk_user_id = getattr(request.state, "clerk_user_id", None)
    session_user_id = getattr(request.state, "session_user_id", None)
    if clerk_user_id or session_user_id:
        return RedirectResponse(url="/dashboard", status_code=303)
    
    # Check if Clerk is enabled
    clerk_enabled = bool(settings.clerk_publishable_key and settings.clerk_issuer)
    
    # NOTE: We no longer clear Clerk cookies server-side.
    # Clerk's frontend SDK handles session management and refresh.
    
    response = templates.TemplateResponse(
        "auth/register.html",
        {
            "request": request,
            "error": None,
            "clerk_enabled": clerk_enabled,
            "clerk_publishable_key": settings.clerk_publishable_key or "",
            "clear_clerk_session": False  # Let Clerk SDK handle session management
        }
    )
    
    return response


@router.post("/register")
async def register(
    request: Request,
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    search_api: str = Form("tavily"),
    db: Session = Depends(get_db)
):
    """Process registration (fallback when Clerk not configured)"""
    from app.main import templates
    
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
    
    return RedirectResponse(url="/dashboard", status_code=303)


@router.get("/logout", name="logout")
async def logout(request: Request):
    """Logout user - clears both session and Clerk cookies"""
    request.session.clear()
    
    response = RedirectResponse(url="/", status_code=303)
    
    # Also clear Clerk cookies to ensure complete logout
    response.delete_cookie("__session")
    response.delete_cookie("__clerk_db_jwt")
    
    return response


# Clerk webhook handler
@router.post("/webhooks/clerk")
async def clerk_webhook(request: Request, db: Session = Depends(get_db)):
    """Handle Clerk webhook events"""
    import json
    import hmac
    import hashlib
    
    if not settings.clerk_webhook_secret:
        raise HTTPException(status_code=500, detail="Clerk webhook not configured")
    
    # Verify webhook signature
    body = await request.body()
    signature = request.headers.get("svix-signature", "")
    
    # Parse event
    try:
        event = json.loads(body)
        event_type = event.get("type")
        data = event.get("data", {})
        
        logger.info(f"Clerk webhook received: {event_type}")
        
        if event_type == "user.created":
            # Create local user record
            user = User(
                clerk_id=data.get("id"),
                username=data.get("username") or data.get("email_addresses", [{}])[0].get("email_address", "").split("@")[0],
                email=data.get("email_addresses", [{}])[0].get("email_address", ""),
                avatar_url=data.get("image_url")
            )
            db.add(user)
            db.commit()
            logger.info(f"Created user from Clerk: {user.username}")
            
        elif event_type == "user.updated":
            # Update local user record
            user = db.query(User).filter(User.clerk_id == data.get("id")).first()
            if user:
                user.email = data.get("email_addresses", [{}])[0].get("email_address", user.email)
                user.avatar_url = data.get("image_url", user.avatar_url)
                db.commit()
                
        elif event_type == "user.deleted":
            # Delete local user record
            user = db.query(User).filter(User.clerk_id == data.get("id")).first()
            if user:
                db.delete(user)
                db.commit()
                logger.info(f"Deleted user from Clerk: {data.get('id')}")
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Clerk webhook error: {e}")
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/settings", response_class=HTMLResponse, name="settings")
async def settings_page(
    request: Request,
    db: Session = Depends(get_db)
):
    """User settings page"""
    from app.main import templates
    import json
    
    user = get_current_user(request, db)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    
    # Parse current preferences
    current_genres = []
    if user.preferred_genres:
        try:
            current_genres = json.loads(user.preferred_genres)
        except:
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

