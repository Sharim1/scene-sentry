"""Test that expired Clerk JWTs trigger a handshake redirect instead of login.

When a Clerk session JWT expires between page navigations, the middleware
should initiate a handshake with Clerk's Frontend API to get a fresh token,
rather than treating the user as unauthenticated. This is the standard
Clerk SSR pattern.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


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
