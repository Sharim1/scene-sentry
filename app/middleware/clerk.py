"""
Clerk Authentication Middleware for FastAPI

This middleware validates Clerk JWT tokens and syncs user data with the local database.
It also handles the Clerk handshake flow for session token refresh.
"""
import logging
import httpx
import base64
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from functools import lru_cache
from urllib.parse import urlencode, urlparse, parse_qs, urlunparse

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response
from sqlalchemy.orm import Session
from jose import jwt, JWTError, jwk
from jose.exceptions import JWKError

from app.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)

# Cache for JWKS (JSON Web Key Set)
_jwks_cache: Optional[Dict[str, Any]] = None
_jwks_cache_time: Optional[datetime] = None
JWKS_CACHE_DURATION_SECONDS = 3600  # 1 hour


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


async def fetch_clerk_jwks() -> Dict[str, Any]:
    """Fetch Clerk's JWKS for token verification"""
    global _jwks_cache, _jwks_cache_time
    
    # Check cache
    if _jwks_cache and _jwks_cache_time:
        age = (datetime.utcnow() - _jwks_cache_time).total_seconds()
        if age < JWKS_CACHE_DURATION_SECONDS:
            return _jwks_cache
    
    if not settings.clerk_issuer:
        logger.warning("CLERK_ISSUER not configured")
        return {}
    
    try:
        jwks_url = f"{settings.clerk_issuer}/.well-known/jwks.json"
        async with httpx.AsyncClient() as client:
            response = await client.get(jwks_url, timeout=10.0)
            response.raise_for_status()
            _jwks_cache = response.json()
            _jwks_cache_time = datetime.utcnow()
            logger.info("Successfully fetched Clerk JWKS")
            return _jwks_cache
    except Exception as e:
        logger.error(f"Failed to fetch Clerk JWKS: {e}")
        return _jwks_cache or {}


def get_signing_key(jwks: Dict[str, Any], token: str) -> Optional[str]:
    """Get the signing key from JWKS that matches the token's kid"""
    try:
        unverified_header = jwt.get_unverified_header(token)
        kid = unverified_header.get("kid")
        
        if not kid:
            return None
        
        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                return jwk.construct(key)
        
        return None
    except Exception as e:
        logger.error(f"Error getting signing key: {e}")
        return None


async def verify_clerk_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify a Clerk JWT token and return the payload"""
    if not settings.clerk_issuer:
        return None
    
    try:
        jwks = await fetch_clerk_jwks()
        if not jwks:
            return None
        
        signing_key = get_signing_key(jwks, token)
        if not signing_key:
            logger.warning("Could not find matching signing key")
            return None
        
        # Verify the token
        payload = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            options={
                "verify_aud": False,  # Clerk doesn't always set audience
                "verify_exp": True,
                "verify_iss": True,
            }
        )
        
        return payload
        
    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        return None
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        return None


async def get_or_create_user_from_clerk(
    db: Session,
    clerk_payload: Dict[str, Any]
) -> Optional["User"]:
    """Get or create a local user from Clerk token payload"""
    from app.models.user import User
    
    clerk_user_id = clerk_payload.get("sub")
    if not clerk_user_id:
        return None
    
    # Try to find existing user by clerk_id
    user = db.query(User).filter(User.clerk_id == clerk_user_id).first()
    
    if user:
        # Update last login
        user.last_login = datetime.utcnow()
        db.commit()
        return user
    
    # Try to find by email (for users who registered before Clerk integration)
    email = clerk_payload.get("email") or clerk_payload.get("primary_email_address")
    if email:
        user = db.query(User).filter(User.email == email).first()
        if user:
            # Link existing user to Clerk
            user.clerk_id = clerk_user_id
            user.last_login = datetime.utcnow()
            
            # Update avatar if available
            if clerk_payload.get("image_url"):
                user.avatar_url = clerk_payload.get("image_url")
            
            db.commit()
            return user
    
    # Create new user
    try:
        # Generate username from email or Clerk data
        username = clerk_payload.get("username")
        if not username and email:
            username = email.split("@")[0]
        if not username:
            username = f"user_{clerk_user_id[:8]}"
        
        # Ensure username is unique
        base_username = username
        counter = 1
        while db.query(User).filter(User.username == username).first():
            username = f"{base_username}_{counter}"
            counter += 1
        
        user = User(
            clerk_id=clerk_user_id,
            username=username,
            email=email or f"{clerk_user_id}@clerk.user",
            avatar_url=clerk_payload.get("image_url"),
            last_login=datetime.utcnow()
        )
        
        db.add(user)
        db.commit()
        db.refresh(user)
        
        logger.info(f"Created new user from Clerk: {user.username}")
        return user
        
    except Exception as e:
        logger.error(f"Failed to create user from Clerk: {e}")
        db.rollback()
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
    
    # Routes that are publicly accessible (for reference - auth is still attempted for all non-static routes)
    # Individual route handlers should check request.state.user and redirect if needed
    PUBLIC_ROUTES = {
        "/",
        "/login",
        "/register",
        "/health",
        "/webhooks/clerk",
        "/favicon.ico",
    }
    
    async def dispatch(self, request: Request, call_next):
        # Initialize user state
        request.state.user = None
        request.state.clerk_user_id = None
        request.state.session_user_id = None
        request.state.handshake_in_progress = False
        
        # Quick check: if Clerk isn't configured, skip Clerk auth entirely
        clerk_configured = bool(settings.clerk_issuer and settings.clerk_publishable_key)
        
        # CRITICAL: Handle Clerk handshake FIRST before any other processing
        # The __clerk_handshake query parameter contains cookie-setting instructions
        if clerk_configured:
            handshake_response = self._handle_clerk_handshake(request)
            if handshake_response:
                return handshake_response
        
        # Check path for static files only - we want to try auth for ALL other routes
        # including public ones, so logged-in users can be identified
        path = request.url.path
        if path.startswith("/static"):
            return await call_next(request)
        
        # Try to get Clerk token from cookie or header
        token = self._extract_token(request) if clerk_configured else None
        
        if token and clerk_configured:
            # Verify Clerk token (uses cached JWKS)
            payload = await verify_clerk_token(token)
            
            if payload:
                # Get database session
                db = next(get_db())
                try:
                    user = await get_or_create_user_from_clerk(db, payload)
                    if user:
                        # Store the user_id and clerk_id for later use
                        # Don't store the ORM object directly as it will be detached
                        request.state.clerk_user_id = user.id
                        request.state.clerk_payload = payload
                finally:
                    db.close()
        
        # Also check session-based auth (fallback)
        if not hasattr(request.state, "clerk_user_id") or request.state.clerk_user_id is None:
            # Check if there's a user_id in session (legacy auth)
            # Note: Use "session" in request.scope instead of hasattr because
            # request.session is a property that raises AssertionError if SessionMiddleware
            # hasn't processed the request yet
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
        
        # Apply each cookie instruction from the handshake
        for cookie_str in cookie_instructions:
            cookie_data = parse_set_cookie_header(cookie_str)
            if not cookie_data.get("name"):
                continue
            
            name = cookie_data["name"]
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
                
                response.set_cookie(
                    key=name,
                    value=value,
                    path=cookie_data.get("path", "/"),
                    domain=cookie_data.get("domain"),
                    max_age=max_age,
                    secure=cookie_data.get("secure", False),
                    httponly=cookie_data.get("httponly", False),
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
        # Check Authorization header
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        
        # Check Clerk session cookie
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
