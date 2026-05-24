"""Test that the login page handles active Clerk sessions correctly.

When a user's JWT expires but they still have an active Clerk session,
the login page should let Clerk.load() refresh the token and redirect
to the dashboard — NOT destroy the session.
"""

from unittest.mock import patch

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


class TestLoginPageAuth:
    def test_login_does_not_destroy_clerk_session(self, client: TestClient):
        """Login page must NOT clear cookies or call Clerk.signOut().
        Clerk's JS SDK handles session refresh — destroying it forces
        unnecessary re-authentication."""
        resp = client.get(
            "/login",
            cookies={"__client_uat": "1234567890"},
            follow_redirects=False,
        )
        assert resp.status_code == 200
        body = resp.content.decode()
        assert "Clerk.signOut" not in body
        assert "__client_uat=;" not in body

    def test_login_redirects_if_clerk_user_active(self, client: TestClient):
        """Login page checks Clerk.user after load and redirects if signed in."""
        resp = client.get("/login", follow_redirects=False)
        assert resp.status_code == 200
        assert b"Clerk.user" in resp.content
        assert b"window.location.replace" in resp.content

    def test_login_renders_normally_without_clerk_cookies(self, client: TestClient):
        """Normal login page (no cookies) renders the sign-in form."""
        resp = client.get("/login", follow_redirects=False)
        assert resp.status_code == 200
        assert b"clerk-sign-in" in resp.content
