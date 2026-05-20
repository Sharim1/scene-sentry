"""
Clerk Authentication Middleware for FastAPI

This middleware validates Clerk JWT tokens and syncs user data with the local database.
It handles the Clerk handshake flow for session token refresh.

Session tokens are verified with the official clerk-backend-api SDK (JWKS from Clerk's API).
"""
import logging
import base64
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from clerk_backend_api.security import verify_token_async, VerifyTokenOptions, TokenVerificationError
from clerk_backend_api.security.types import TokenVerificationErrorReason

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)


def decode_handshake_jwt(handshake_token: str) -> Optional[List[str]]:
    """
    Decode the Clerk handshake JWT and extract cookie instructions.
    The handshake JWT is NOT verified - it contains public cookie-setting instructions.
    """
    try:
        # Split the JWT and decode the payload (second part)
        parts = handshake_token.split(".")
        if len(parts) != 3:
            logger.warning("Invalid handshake JWT format")
            return None
        
        # Decode payload (add padding if needed)
        payload_b64 = parts[1]
        padding = 4 - len(payload_b64) % 4
        if padding != 4:
            payload_b64 += "=" * padding
        
        payload_json = base64.urlsafe_b64decode(payload_b64)
        payload = json.loads(payload_json)
        
        # Extract handshake array (cookie instructions)
        handshake_cookies = payload.get("handshake", [])
        if handshake_cookies:
            logger.debug(f"Extracted {len(handshake_cookies)} cookie instructions from handshake")
        return handshake_cookies
        
    except Exception as e:
        logger.error(f"Failed to decode handshake JWT: {e}")
        return None


def parse_set_cookie_header(cookie_str: str) -> Dict[str, Any]:
    """Parse a Set-Cookie header string into components"""
    parts = cookie_str.split(";")
    if not parts:
        return {}
    
    # First part is name=value
    name_value = parts[0].strip()
    if "=" not in name_value:
        return {}
    
    name, value = name_value.split("=", 1)
    result = {"name": name.strip(), "value": value}
    
    # Parse attributes
    for part in parts[1:]:
        part = part.strip()
        if "=" in part:
            attr_name, attr_value = part.split("=", 1)
            attr_name = attr_name.strip().lower()
            result[attr_name] = attr_value.strip()
        else:
            # Boolean attributes like Secure, HttpOnly
            result[part.lower()] = True
    
    return result


def _log_token_verification_failure(reason: TokenVerificationErrorReason) -> None:
    if reason == TokenVerificationErrorReason.TOKEN_EXPIRED:
        logger.debug("Clerk token has expired")
    elif reason == TokenVerificationErrorReason.TOKEN_INVALID_AUTHORIZED_PARTIES:
        logger.warning("Clerk token azp not in authorized parties")
    elif reason in (
        TokenVerificationErrorReason.JWK_FAILED_TO_LOAD,
        TokenVerificationErrorReason.JWK_REMOTE_INVALID,
        TokenVerificationErrorReason.SERVER_ERROR,
    ):
        logger.error("Clerk token verification failed: %s", reason.value[1])
    else:
        logger.warning("Clerk token verification failed: %s", reason.value[1])


async def verify_clerk_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Verify a Clerk session JWT using clerk-backend-api and return the payload.
    """
    if not settings.clerk_secret_key:
        logger.warning("CLERK_SECRET_KEY not configured, skipping token verification")
        return None

    parties = settings.clerk_authorized_parties_list
    options = VerifyTokenOptions(
        secret_key=settings.clerk_secret_key,
        authorized_parties=parties if parties else None,
    )
    try:
        return await verify_token_async(token, options)
    except TokenVerificationError as e:
        _log_token_verification_failure(e.reason)
        return None
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        return None


def fetch_clerk_user_email(clerk_user_id: str) -> Optional[str]:
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
            # Fallback: return the first email if primary isn't flagged
            return clerk_user.email_addresses[0].email_address
    except Exception as exc:
        logger.warning("Could not fetch email from Clerk API for %s: %s", clerk_user_id, exc)
        return None


def _is_placeholder_email(email: Optional[str]) -> bool:
    return bool(email and email.endswith("@clerk.user"))


def _is_placeholder_username(username: Optional[str]) -> bool:
    return bool(username and username.startswith("user_user_"))


def generate_unique_username(clerk_payload: Dict[str, Any], email: Optional[str] = None, attempt: int = 0) -> str:
    """Generate a unique username from Clerk payload"""
    if not email:
        email = clerk_payload.get("email") or clerk_payload.get("primary_email_address")
    clerk_user_id = clerk_payload.get("sub", "")
    
    username = clerk_payload.get("username")
    if not username and email:
        username = email.split("@")[0]
    if not username:
        # clerk_user_id is like "user_32NZl491..." — strip the "user_" prefix
        short_id = clerk_user_id.removeprefix("user_")[:8]
        username = f"user_{short_id}"
    
    if attempt > 0:
        username = f"{username}_{attempt}"
    
    return username


async def get_or_create_user_from_clerk(
    db: Session,
    clerk_payload: Dict[str, Any]
) -> Optional["User"]:
    """
    Get or create a local user from Clerk token payload.
    
    Uses retry logic to handle race conditions in username generation.
    Falls back to the Clerk Backend API to resolve the user's real email
    when the JWT doesn't include one.
    """
    from app.models.user import User
    
    clerk_user_id = clerk_payload.get("sub")
    if not clerk_user_id:
        logger.warning("Clerk payload missing 'sub' claim")
        return None
    
    # Try to find existing user by clerk_id
    user = db.query(User).filter(User.clerk_id == clerk_user_id).first()
    
    if user:
        user.last_login = datetime.now(timezone.utc)

        # Backfill real email if still a placeholder
        if _is_placeholder_email(user.email):
            real_email = fetch_clerk_user_email(clerk_user_id)
            if real_email:
                user.email = real_email
                logger.info("Backfilled real email for user %s", user.username)

        # Backfill username if it has the double-prefix bug
        if _is_placeholder_username(user.username):
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
            user.last_login = datetime.now(timezone.utc)
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
                last_login=datetime.now(timezone.utc)
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


class ClerkAuthMiddleware(BaseHTTPMiddleware):
    """
    Middleware that validates Clerk JWT tokens from cookies or Authorization header.
    Sets request.state.user if authentication is successful.
    
    Also handles the Clerk handshake flow:
    - When Clerk redirects with __clerk_handshake query parameter
    - The handshake JWT contains cookie-setting instructions
    - We set those cookies and redirect back without the parameter
    """
    
    async def dispatch(self, request: Request, call_next):
        # Initialize user state
        request.state.user = None
        request.state.clerk_user_id = None
        request.state.session_user_id = None
        request.state.clerk_payload = None
        request.state.handshake_in_progress = False
        
        # Quick check: if Clerk isn't configured, skip Clerk auth entirely
        clerk_configured = settings.is_clerk_configured
        
        # CRITICAL: Handle Clerk handshake FIRST before any other processing
        # The __clerk_handshake query parameter contains cookie-setting instructions
        if clerk_configured:
            handshake_response = self._handle_clerk_handshake(request)
            if handshake_response:
                return handshake_response
        
        path = request.url.path
        if path.startswith("/static") or path in ("/favicon.ico", "/health"):
            return await call_next(request)
        
        # Try to get Clerk token from cookie or header
        token = self._extract_token(request) if clerk_configured else None
        
        if token and clerk_configured:
            # Verify Clerk token (uses cached JWKS)
            payload = await verify_clerk_token(token)
            
            if payload:
                # Get database session and sync user
                db_gen = get_db()
                db = next(db_gen)
                try:
                    user = await get_or_create_user_from_clerk(db, payload)
                    if user:
                        # Store the user_id and clerk_id for later use
                        # Don't store the ORM object directly as it will be detached
                        request.state.clerk_user_id = user.id
                        request.state.clerk_payload = payload
                except Exception as e:
                    logger.error(f"Error processing Clerk user: {e}")
                finally:
                    try:
                        next(db_gen, None)  # Cleanup generator
                    except StopIteration:
                        pass
                    db.close()
        
        # Also check session-based auth (fallback when Clerk not configured)
        if request.state.clerk_user_id is None and not clerk_configured:
            # Check if there's a user_id in session (legacy auth)
            if "session" in request.scope and request.scope["session"].get("user_id"):
                request.state.session_user_id = request.scope["session"].get("user_id")
        
        response = await call_next(request)
        return response
    
    def _handle_clerk_handshake(self, request: Request) -> Optional[Response]:
        """
        Handle Clerk's handshake flow.
        
        When Clerk authenticates a user, it redirects to your app with a 
        __clerk_handshake query parameter. This JWT contains Set-Cookie 
        instructions that need to be applied.
        
        Returns a redirect response if handshake is handled, None otherwise.
        """
        # Check for handshake query parameter
        handshake_token = request.query_params.get("__clerk_handshake")
        if not handshake_token:
            return None
        
        logger.info("Processing Clerk handshake...")
        
        # Decode the handshake JWT to get cookie instructions
        cookie_instructions = decode_handshake_jwt(handshake_token)
        if not cookie_instructions:
            logger.warning("Could not decode handshake JWT, continuing without setting cookies")
            # Still redirect to remove the handshake parameter
            return self._redirect_without_handshake(request)
        
        # Build redirect URL without the __clerk_handshake parameter
        redirect_url = self._get_url_without_handshake(request)
        response = RedirectResponse(url=redirect_url, status_code=307)
        
        ALLOWED_HANDSHAKE_COOKIES = {"__session", "__client_uat", "__clerk_db_jwt"}

        for cookie_str in cookie_instructions:
            cookie_data = parse_set_cookie_header(cookie_str)
            if not cookie_data.get("name"):
                continue
            
            name = cookie_data["name"]
            if name not in ALLOWED_HANDSHAKE_COOKIES:
                logger.warning(f"Handshake: rejecting unrecognized cookie {name}")
                continue
            value = cookie_data.get("value", "")
            
            # Check if this is a delete instruction (expires in past or empty value with past expiry)
            is_delete = "expires" in cookie_data and "1970" in str(cookie_data.get("expires", ""))
            
            if is_delete:
                # Delete the cookie
                response.delete_cookie(
                    key=name,
                    path=cookie_data.get("path", "/"),
                    domain=cookie_data.get("domain"),
                )
                logger.debug(f"Handshake: deleting cookie {name}")
            else:
                # Set the cookie
                max_age = None
                if "max-age" in cookie_data:
                    try:
                        max_age = int(cookie_data["max-age"])
                    except ValueError:
                        pass
                
                is_production = settings.env == "production"
                response.set_cookie(
                    key=name,
                    value=value,
                    path=cookie_data.get("path", "/"),
                    domain=cookie_data.get("domain"),
                    max_age=max_age,
                    secure=cookie_data.get("secure", False) or is_production,
                    httponly=cookie_data.get("httponly", True),
                    samesite=cookie_data.get("samesite", "lax").lower() if cookie_data.get("samesite") else "lax",
                )
                logger.debug(f"Handshake: setting cookie {name}")
        
        logger.info(f"Clerk handshake processed, redirecting to {redirect_url}")
        return response
    
    def _get_url_without_handshake(self, request: Request) -> str:
        """Build the current URL without the __clerk_handshake parameter"""
        parsed = urlparse(str(request.url))
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        
        # Remove handshake parameter
        query_params.pop("__clerk_handshake", None)
        
        # Rebuild query string
        new_query = urlencode(query_params, doseq=True)
        
        # Rebuild URL
        new_url = urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment
        ))
        
        return new_url
    
    def _redirect_without_handshake(self, request: Request) -> Response:
        """Redirect to the same URL without the handshake parameter"""
        redirect_url = self._get_url_without_handshake(request)
        return RedirectResponse(url=redirect_url, status_code=307)
    
    def _extract_token(self, request: Request) -> Optional[str]:
        """Extract Clerk token from request"""
        # Check Authorization header first (for API requests)
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        
        # Check Clerk session cookie (for browser requests)
        # Clerk uses __session cookie by default
        token = request.cookies.get("__session")
        if token:
            return token
        
        # Also check __clerk_db_jwt cookie
        token = request.cookies.get("__clerk_db_jwt")
        if token:
            return token
        
        return None


def get_clerk_user_id(request: Request) -> Optional[int]:
    """Get the authenticated user's ID from request state"""
    return getattr(request.state, "clerk_user_id", None) or getattr(request.state, "session_user_id", None)
