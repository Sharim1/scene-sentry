"""
Clerk Authentication Middleware for FastAPI

Thin middleware that verifies Clerk JWT tokens and attaches user identity to
the request.  User creation/update logic lives in
``app.services.identity_sync``.

Session tokens are verified with the official clerk-backend-api SDK (JWKS).
"""

import base64
import json
import logging
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from clerk_backend_api.security import TokenVerificationError, VerifyTokenOptions, verify_token_async
from clerk_backend_api.security.types import TokenVerificationErrorReason
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import RedirectResponse, Response

from app.config import settings
from app.database import get_db
from app.services.identity_sync import (
    get_or_create_user,
    is_placeholder_email,
    is_placeholder_username,
)

logger = logging.getLogger(__name__)


def decode_handshake_jwt(handshake_token: str) -> list[str] | None:
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


def parse_set_cookie_header(cookie_str: str) -> dict[str, Any]:
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


async def verify_clerk_token(token: str) -> dict[str, Any] | None:
    """
    Verify a Clerk session JWT using clerk-backend-api and return the payload.

    Re-raises TokenVerificationError (after logging) so the caller can tell an
    expired token apart from any other failure — the middleware uses that to
    decide whether a handshake retry is worth attempting. A non-Clerk error
    still just returns None.
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
        raise
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        return None


# Backward-compat aliases (prefer importing from app.services.identity_sync).
_is_placeholder_email = is_placeholder_email
_is_placeholder_username = is_placeholder_username
get_or_create_user_from_clerk = get_or_create_user


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
            # Verify Clerk token (uses cached JWKS). An expired token is not
            # the same as a missing/invalid one: the browser had a real
            # session, so a handshake retry is always worth attempting, even
            # when __client_uat isn't a reliable signal in this environment
            # (Clerk Development instances lean on __clerk_db_jwt instead —
            # see _should_initiate_handshake).
            token_expired = False
            try:
                payload = await verify_clerk_token(token)
            except TokenVerificationError as e:
                payload = None
                token_expired = e.reason == TokenVerificationErrorReason.TOKEN_EXPIRED

            if payload:
                # Get database session and sync user
                db_gen = get_db()
                db = next(db_gen)
                try:
                    user = await get_or_create_user_from_clerk(db, payload)
                    if user:
                        request.state.clerk_user_id = user.id
                        request.state.clerk_payload = payload
                except Exception as e:
                    logger.error(f"Error processing Clerk user: {e}")
                finally:
                    try:
                        next(db_gen, None)
                    except StopIteration:
                        pass
                    db.close()
            elif self._should_initiate_handshake(request, force=token_expired):
                return self._initiate_handshake(request)

        elif clerk_configured and not token and self._should_initiate_handshake(request):
            return self._initiate_handshake(request)

        # Also check session-based auth (fallback when Clerk not configured)
        if request.state.clerk_user_id is None and not clerk_configured:
            if "session" in request.scope and request.scope["session"].get("user_id"):
                request.state.session_user_id = request.scope["session"].get("user_id")

        response = await call_next(request)
        return response

    def _handle_clerk_handshake(self, request: Request) -> Response | None:
        """
        Handle Clerk's handshake flow.

        Clerk's Frontend API hands back the handshake payload as a
        short-lived, HttpOnly __clerk_handshake COOKIE on the redirect
        response (`Set-Cookie: __clerk_handshake=<jwt>; Domain=...;
        Max-Age=70`) — not as a __clerk_handshake query parameter appended to
        the redirect's Location. The browser just sends that cookie back on
        the very next request like any other cookie.

        We still check the query parameter too, for compatibility with any
        flow that might append it there, but the cookie is the one that
        actually arrives in practice. Missing it here means we never decode
        the handshake JWT, never apply its __client_uat=0 / __session-clear
        instructions, and the next request looks identical to the one that
        triggered the handshake in the first place — causing an infinite
        redirect loop against Clerk's FAPI for any browser with a truthy
        __client_uat and no valid __session (i.e. every real sign-in, not
        just a stale one).

        Returns a redirect response if handshake is handled, None otherwise.
        """
        handshake_token = request.query_params.get("__clerk_handshake") or request.cookies.get("__clerk_handshake")
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
                    httponly=cookie_data.get("httponly", False),
                    samesite=cookie_data.get("samesite", "lax").lower() if cookie_data.get("samesite") else "lax",
                )
                logger.debug(f"Handshake: setting cookie {name}")

        # __clerk_handshake itself is never in ALLOWED_HANDSHAKE_COOKIES (it's
        # not a session cookie), so Clerk's own delete-instruction for it gets
        # filtered out above. Clear it explicitly so a page load within its
        # ~70s Max-Age can't re-trigger processing of an already-consumed
        # handshake token.
        response.delete_cookie(key="__clerk_handshake", path="/", domain=request.url.hostname)

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
        new_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))

        return new_url

    def _redirect_without_handshake(self, request: Request) -> Response:
        """Redirect to the same URL without the handshake parameter"""
        redirect_url = self._get_url_without_handshake(request)
        return RedirectResponse(url=redirect_url, status_code=307)

    def _should_initiate_handshake(self, request: Request, force: bool = False) -> bool:
        """Check whether we should redirect to Clerk's FAPI for a token refresh.

        Only for GET page navigations — never for POST/API/static requests.

        __client_uat normally has to look like an active session before we
        bother, so a visitor who was never signed in doesn't get redirected
        through Clerk. `force=True` skips the "__client_uat is missing"
        version of that check: we already know the request carried an actual
        session token that just expired (see the caller), which is a
        stronger signal than __client_uat — and on a Clerk Development
        instance, __client_uat isn't guaranteed to be set the way it is on
        Production (Clerk's "dev browser" mechanism uses __clerk_db_jwt via
        querystring instead), so requiring it here would make the handshake
        retry miss its one real use case on dev instances.

        __client_uat == "0" is different and always wins, force or not:
        it's Clerk's own explicit "this browser is signed out" signal, sent
        back by the handshake we just completed. Treating force=True as a
        license to ignore it causes an infinite redirect loop against
        Clerk's FAPI whenever the browser's session token can never be
        refreshed (e.g. it was issued by an instance we've since migrated
        away from) — every retry re-expires, forces another handshake,
        Clerk says "signed out" again, and we'd keep ignoring that forever.
        """
        if request.method != "GET":
            return False

        client_uat = request.cookies.get("__client_uat")
        if client_uat == "0":
            return False
        if not force and not client_uat:
            return False

        if not settings.clerk_issuer:
            return False

        path = request.url.path
        if path.startswith("/api/") or path.startswith("/webhooks/"):
            return False
        return path not in ("/login", "/register", "/logout", "/health", "/favicon.ico")

    def _initiate_handshake(self, request: Request) -> Response:
        """Redirect to Clerk's Frontend API to refresh the session token."""
        fapi_url = settings.clerk_issuer.rstrip("/")
        current_url = str(request.url)
        redirect_url = f"{fapi_url}/v1/client/handshake?redirect_url={current_url}"
        logger.debug("Initiating Clerk handshake for %s", request.url.path)
        return RedirectResponse(url=redirect_url, status_code=307)

    def _extract_token(self, request: Request) -> str | None:
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


def get_clerk_user_id(request: Request) -> int | None:
    """Get the authenticated user's ID from request state"""
    return getattr(request.state, "clerk_user_id", None) or getattr(request.state, "session_user_id", None)
