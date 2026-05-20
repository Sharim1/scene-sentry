"""Shared FastAPI dependency type aliases and auth helpers."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models.user import User

DbDep = Annotated[Session, Depends(get_db)]


def get_current_user(request: Request, db: DbDep) -> User | None:
    """
    Get current user from Clerk middleware or session fallback.

    Priority:
    1. Clerk authentication (if configured)
    2. Session-based authentication (fallback for dev/non-Clerk setups)
    """
    clerk_user_id = getattr(request.state, "clerk_user_id", None)
    if clerk_user_id:
        user = db.query(User).filter(User.id == clerk_user_id).first()
        if user:
            request.state.user = user
            return user

    if not settings.is_clerk_configured:
        session_user_id = getattr(request.state, "session_user_id", None)
        if session_user_id:
            user = db.query(User).filter(User.id == session_user_id).first()
            if user:
                request.state.user = user
                return user

        if hasattr(request, "session"):
            user_id = request.session.get("user_id")
            if user_id:
                user = db.query(User).filter(User.id == user_id).first()
                if user:
                    request.state.user = user
                    return user

    return None


def require_auth(request: Request, db: DbDep) -> User:
    """Require authenticated user -- raises 401 if not authenticated."""
    user = get_current_user(request, db)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


OptionalUserDep = Annotated[User | None, Depends(get_current_user)]
RequireAuthDep = Annotated[User, Depends(require_auth)]
