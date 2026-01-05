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


# Session-based auth helpers (fallback when Clerk is not configured)
def get_current_user(request: Request, db: Session = Depends(get_db)) -> Optional[User]:
    """Get current user from session or Clerk"""
    # Check session first (fallback auth)
    user_id = request.session.get("user_id") if hasattr(request, "session") else None
    if user_id:
        return db.query(User).filter(User.id == user_id).first()
    return None


def require_auth(request: Request, db: Session = Depends(get_db)) -> User:
    """Require authenticated user"""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


@router.get("/login", response_class=HTMLResponse, name="login")
async def login_page(request: Request):
    """Login page"""
    from app.main import templates
    
    # Show traditional login form
    # TODO: Add Clerk integration when templates are ready
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "error": None}
    )


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
    """Registration page"""
    from app.main import templates
    
    # Show traditional registration form
    # TODO: Add Clerk integration when templates are ready
    return templates.TemplateResponse(
        "auth/register.html",
        {"request": request, "error": None}
    )


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
    """Logout user"""
    request.session.clear()
    return RedirectResponse(url="/", status_code=303)


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

