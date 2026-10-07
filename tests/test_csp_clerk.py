"""Regression guard for SCE-49: the CSP allow-lists the production Clerk host.

Clerk serves its JS/XHR/frames from the Frontend API host encoded in
`CLERK_ISSUER`. On a production instance this is a custom domain
(e.g. `clerk.scenesentry.com`), not `*.clerk.accounts.dev`. If the CSP only
lists the dev host, production Clerk is blocked by the browser. These tests
lock in that the CSP is derived from `CLERK_ISSUER` and that the security
headers actually reach responses through the middleware.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import _build_content_security_policy


@pytest.fixture()
def client():
    from app.main import app

    with (
        patch("app.main.init_db"),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        yield c


class TestCspClerkHost:
    def test_dev_host_always_present(self):
        csp = _build_content_security_policy()
        assert "https://*.clerk.accounts.dev" in csp

    def test_production_fapi_host_is_allowlisted(self):
        with patch.object(settings, "clerk_issuer", "https://clerk.scenesentry.com"):
            csp = _build_content_security_policy()
        # The host must reach every Clerk fetch directive; otherwise the browser
        # blocks either the script load, its XHR, or the sign-in frame.
        assert csp.count("https://clerk.scenesentry.com") >= 3
        assert "https://clerk.scenesentry.com" in csp.split("connect-src")[0]

    def test_no_duplicate_when_issuer_is_dev_instance(self):
        with patch.object(settings, "clerk_issuer", "https://relaxed-cat-12.clerk.accounts.dev"):
            csp = _build_content_security_policy()
        # The dev instance host is covered by the wildcard; don't add it twice.
        assert "relaxed-cat-12.clerk.accounts.dev" not in csp
        assert "https://*.clerk.accounts.dev" in csp

    def test_absent_issuer_still_yields_valid_csp(self):
        with patch.object(settings, "clerk_issuer", None):
            csp = _build_content_security_policy()
        assert "default-src 'self'" in csp
        assert "https://*.clerk.accounts.dev" in csp

    def test_bare_host_issuer_is_parsed(self):
        # Tolerate a scheme-less CLERK_ISSUER without leaking the path/scheme.
        with patch.object(settings, "clerk_issuer", "clerk.scenesentry.com"):
            csp = _build_content_security_policy()
        assert "https://clerk.scenesentry.com" in csp


class TestSecurityHeadersResponsePath:
    """Exercise the real middleware response path, not just the CSP builder."""

    def test_csp_header_served_on_response(self, client):
        csp = client.get("/health").headers.get("Content-Security-Policy", "")
        assert "default-src 'self'" in csp
        assert "https://*.clerk.accounts.dev" in csp

    def test_hsts_absent_outside_production(self, client):
        # settings.env defaults to development under test.
        assert "Strict-Transport-Security" not in client.get("/health").headers

    def test_hsts_present_in_production(self, client):
        with patch.object(settings, "env", "production"):
            hsts = client.get("/health").headers.get("Strict-Transport-Security")
        assert hsts == "max-age=63072000; includeSubDomains"

    def test_csrf_cookie_issued_on_non_exempt_response(self, client):
        # CSRFMiddleware is wired into the response path: a non-exempt GET mints
        # the double-submit token cookie. (/health is CSRF-exempt, so use /.)
        assert "csrftoken" in client.get("/").cookies
