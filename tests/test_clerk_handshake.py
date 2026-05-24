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
    from app.main import app

    with (
        patch("app.main.init_db"),
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
