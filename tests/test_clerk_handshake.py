"""Test that expired Clerk JWTs trigger a handshake redirect instead of login.

When a Clerk session JWT expires between page navigations, the middleware
should initiate a handshake with Clerk's Frontend API to get a fresh token,
rather than treating the user as unauthenticated. This is the standard
Clerk SSR pattern.
"""

import base64
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


def _fake_handshake_jwt(cookie_instructions: list[str]) -> str:
    """Build a fake (unsigned) handshake JWT like Clerk's FAPI issues.

    Our decoder never verifies the signature — it only reads the payload —
    so a throwaway header/signature is fine for testing.
    """
    header = base64.urlsafe_b64encode(b'{"alg":"RS256","typ":"JWT"}').rstrip(b"=").decode()
    payload = base64.urlsafe_b64encode(json.dumps({"handshake": cookie_instructions}).encode()).rstrip(b"=").decode()
    return f"{header}.{payload}.fakesignature"


@pytest.fixture()
def client():
    from app.config import settings
    from app.main import app

    with (
        patch("app.main.init_db"),
        patch.object(settings, "clerk_secret_key", "sk_test_fake"),
        patch.object(settings, "clerk_publishable_key", "pk_test_fake"),
        patch.object(settings, "clerk_issuer", "https://clerk.example.com"),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        yield c


class TestExpiredTokenHandshake:
    def test_expired_token_with_client_uat_triggers_handshake_redirect(self, client: TestClient):
        """When __session is present but expired and __client_uat indicates an
        active client session, redirect to Clerk FAPI for token refresh."""
        with patch(
            "app.middleware.clerk.verify_clerk_token",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(
                "/dashboard",
                cookies={
                    "__session": "expired.jwt.token",
                    "__client_uat": "1716500000",
                },
                follow_redirects=False,
            )

        assert resp.status_code == 307
        location = resp.headers["location"]
        assert "/v1/client/handshake" in location
        assert "redirect_url" in location

    def test_expired_token_without_client_uat_still_handshakes(self, client: TestClient):
        """An expired __session with no (or stale) __client_uat still gets a
        handshake retry, not a login redirect.

        __client_uat isn't a reliable signal on a Clerk Development instance
        — Clerk's "dev browser" mechanism there uses __clerk_db_jwt via
        querystring instead (see Clerk's docs on managing environments). An
        expired token is itself proof the browser had a real session, so
        that alone should be enough to retry, regardless of __client_uat.
        """
        from clerk_backend_api.security.types import TokenVerificationError, TokenVerificationErrorReason

        with patch(
            "app.middleware.clerk.verify_clerk_token",
            new_callable=AsyncMock,
            side_effect=TokenVerificationError(TokenVerificationErrorReason.TOKEN_EXPIRED),
        ):
            resp = client.get(
                "/dashboard",
                cookies={"__session": "expired.jwt.token"},  # no __client_uat at all
                follow_redirects=False,
            )

        assert resp.status_code == 307
        assert "/v1/client/handshake" in resp.headers["location"]

    def test_non_expiry_verification_failure_without_client_uat_goes_to_login(self, client: TestClient):
        """A token that's invalid for some other reason (not expiry), with no
        __client_uat, should NOT force a handshake retry — that's reserved
        for the one case where we know for certain the browser had a real,
        merely-expired session."""
        from clerk_backend_api.security.types import TokenVerificationError, TokenVerificationErrorReason

        with patch(
            "app.middleware.clerk.verify_clerk_token",
            new_callable=AsyncMock,
            side_effect=TokenVerificationError(TokenVerificationErrorReason.TOKEN_INVALID_SIGNATURE),
        ):
            resp = client.get(
                "/dashboard",
                cookies={"__session": "garbage"},
                follow_redirects=False,
            )

        assert resp.status_code == 303
        assert resp.headers["location"] == "/login?next=/dashboard"

    def test_expired_token_with_client_uat_zero_goes_to_login_not_loop(self, client: TestClient):
        """An expired/unrefreshable __session alongside __client_uat=0 must
        NOT force another handshake.

        __client_uat=0 is Clerk's own explicit "this browser is signed out"
        signal, sent back by a handshake that already ran (e.g. because the
        session token was issued by an instance we've since migrated away
        from and can never be refreshed). Forcing another handshake anyway
        ignores that signal and loops forever against Clerk's FAPI —
        reproduces the ERR_TOO_MANY_REDIRECTS bug.
        """
        from clerk_backend_api.security.types import TokenVerificationError, TokenVerificationErrorReason

        with patch(
            "app.middleware.clerk.verify_clerk_token",
            new_callable=AsyncMock,
            side_effect=TokenVerificationError(TokenVerificationErrorReason.TOKEN_EXPIRED),
        ):
            resp = client.get(
                "/dashboard",
                cookies={"__session": "stale.unrefreshable.token", "__client_uat": "0"},
                follow_redirects=False,
            )

        assert resp.status_code == 303
        assert resp.headers["location"] == "/login?next=/dashboard"

    def test_handshake_delivered_as_cookie_is_processed_not_ignored(self, client: TestClient):
        """Clerk's FAPI hands back the handshake payload as a __clerk_handshake
        COOKIE on the redirect response, not as a query parameter appended to
        the Location. Missing that meant we never decoded it, never applied
        __client_uat=0 / cleared __session, and the next request looked
        identical to the one that triggered the handshake — causing an
        infinite loop against Clerk's FAPI for every real sign-in (not just
        a stale one). This reproduces the live ERR_TOO_MANY_REDIRECTS bug.
        """
        handshake_jwt = _fake_handshake_jwt(
            [
                "__client_uat=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Secure; SameSite=Lax",
                "__client_uat=0; Path=/; Domain=scenesentry.com; Max-Age=315360000; Secure; SameSite=Lax",
                "__session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Secure; SameSite=Lax",
            ]
        )

        resp = client.get(
            "/dashboard",
            cookies={"__client_uat": "1716500000", "__clerk_handshake": handshake_jwt},
            follow_redirects=False,
        )

        assert resp.status_code == 307
        # The redirect target must not still be carrying a handshake param —
        # and critically, the client_uat=0 instruction must actually have
        # been applied, which is what stops the loop on the next request.
        set_cookie_headers = resp.headers.get_list("set-cookie")
        assert any("__client_uat=0" in h for h in set_cookie_headers)
        assert any(h.startswith("__session=") for h in set_cookie_headers)

    def test_no_cookies_at_all_goes_to_login(self, client: TestClient):
        """No Clerk cookies at all → normal redirect to login."""
        resp = client.get("/dashboard", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login?next=/dashboard"

    def test_client_uat_zero_goes_to_login(self, client: TestClient):
        """__client_uat=0 means the user explicitly signed out — don't handshake."""
        resp = client.get(
            "/dashboard",
            cookies={"__client_uat": "0"},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login?next=/dashboard"

    def test_api_requests_get_401_not_handshake(self, client: TestClient):
        """API endpoints should return 401, not redirect to handshake."""
        with patch(
            "app.middleware.clerk.verify_clerk_token",
            new_callable=AsyncMock,
            return_value=None,
        ):
            resp = client.get(
                "/api/search?q=test",
                cookies={
                    "__session": "expired.jwt.token",
                    "__client_uat": "1716500000",
                },
                follow_redirects=False,
            )

        assert resp.status_code == 401

    def test_static_assets_skip_handshake(self, client: TestClient):
        """Static files should never trigger a handshake redirect."""
        resp = client.get(
            "/static/js/app.js",
            cookies={
                "__session": "expired.jwt.token",
                "__client_uat": "1716500000",
            },
            follow_redirects=False,
        )
        # Should serve the file or 404, not redirect
        assert resp.status_code in (200, 304, 404)
