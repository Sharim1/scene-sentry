"""
Identity sync — owns user creation, update, and email resolution via Clerk.

Extracted from the auth middleware so that CLI tools, webhooks, and tests
can call identity-sync logic without importing HTTP middleware.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.models.user import User

logger = logging.getLogger(__name__)


def fetch_clerk_user_email(clerk_user_id: str) -> str | None:
    """Call the Clerk Backend API to get a user's primary email address.

    Returns the email string, or None on any failure.
    """
    if not settings.clerk_secret_key:
        return None
    try:
        from clerk_backend_api import Clerk

        with Clerk(bearer_auth=settings.clerk_secret_key) as client:
            clerk_user = client.users.get(user_id=clerk_user_id)
            if not clerk_user or not clerk_user.email_addresses:
                return None

            primary_id = clerk_user.primary_email_address_id
            for ea in clerk_user.email_addresses:
                if ea.id == primary_id:
                    return ea.email_address
            return clerk_user.email_addresses[0].email_address
    except Exception as exc:
        logger.warning("Could not fetch email from Clerk API for %s: %s", clerk_user_id, exc)
        return None


def is_placeholder_email(email: str | None) -> bool:
    return bool(email and email.endswith("@clerk.user"))


def is_placeholder_username(username: str | None) -> bool:
    return bool(username and username.startswith("user_user_"))


def generate_unique_username(clerk_payload: dict[str, Any], email: str | None = None, attempt: int = 0) -> str:
    """Generate a unique username from Clerk payload."""
    if not email:
        email = clerk_payload.get("email") or clerk_payload.get("primary_email_address")
    clerk_user_id = clerk_payload.get("sub", "")

    username = clerk_payload.get("username")
    if not username and email:
        username = email.split("@")[0]
    if not username:
        short_id = clerk_user_id.removeprefix("user_")[:8]
        username = f"user_{short_id}"

    if attempt > 0:
        username = f"{username}_{attempt}"

    return username


async def get_or_create_user(db: Session, clerk_payload: dict[str, Any]) -> User | None:
    """Get or create a local user from Clerk token payload.

    Uses retry logic to handle race conditions in username generation.
    Falls back to the Clerk Backend API to resolve the user's real email
    when the JWT doesn't include one.
    """
    clerk_user_id = clerk_payload.get("sub")
    if not clerk_user_id:
        logger.warning("Clerk payload missing 'sub' claim")
        return None

    user = db.query(User).filter(User.clerk_id == clerk_user_id).first()

    if user:
        user.last_login = datetime.now(UTC)

        if is_placeholder_email(user.email):
            real_email = fetch_clerk_user_email(clerk_user_id)
            if real_email:
                user.email = real_email
                logger.info("Backfilled real email for user %s", user.username)

        if is_placeholder_username(user.username):
            better = generate_unique_username(clerk_payload, email=user.email)
            if better != user.username:
                user.username = better
                logger.info("Fixed username to %s", better)

        try:
            db.commit()
        except Exception as e:
            logger.error(f"Failed to update user on login: {e}")
            db.rollback()
        return user

    # Resolve email: try JWT claims first, then Backend API
    email = clerk_payload.get("email") or clerk_payload.get("primary_email_address")
    if not email:
        email = fetch_clerk_user_email(clerk_user_id)

    # Try to find by email (for users who registered before Clerk integration)
    if email:
        user = db.query(User).filter(User.email == email).first()
        if user:
            user.clerk_id = clerk_user_id
            user.last_login = datetime.now(UTC)
            if clerk_payload.get("image_url"):
                user.avatar_url = clerk_payload.get("image_url")
            try:
                db.commit()
            except Exception as e:
                logger.error(f"Failed to link user to Clerk: {e}")
                db.rollback()
            return user

    # Create new user with retry logic for uniqueness conflicts
    max_retries = 5
    for attempt in range(max_retries):
        try:
            username = generate_unique_username(clerk_payload, email=email, attempt=attempt)

            user = User(
                clerk_id=clerk_user_id,
                username=username,
                email=email or f"{clerk_user_id}@clerk.user",
                avatar_url=clerk_payload.get("image_url"),
                last_login=datetime.now(UTC),
            )

            db.add(user)
            db.commit()
            db.refresh(user)

            logger.info(f"Created new user from Clerk: {user.username} (clerk_id: {clerk_user_id[:8]}...)")
            return user

        except IntegrityError as e:
            db.rollback()
            if attempt == max_retries - 1:
                logger.error(f"Failed to create user after {max_retries} attempts: {e}")
                return None
            logger.debug(f"Username collision on attempt {attempt + 1}, retrying...")
            continue
        except Exception as e:
            logger.error(f"Failed to create user from Clerk: {e}")
            db.rollback()
            return None

    return None
