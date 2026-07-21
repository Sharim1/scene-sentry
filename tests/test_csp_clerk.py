"""Regression guard for SCE-49: the CSP allow-lists the production Clerk host.

Clerk serves its JS/XHR/frames from the Frontend API host encoded in
`CLERK_ISSUER`. On a production instance this is a custom domain
(e.g. `clerk.scenesentry.com`), not `*.clerk.accounts.dev`. If the CSP only
lists the dev host, production Clerk is blocked by the browser. These tests
lock in that the CSP is derived from `CLERK_ISSUER`.
"""

from unittest.mock import patch

from app.config import settings
from app.main import _build_content_security_policy


class TestCspClerkHost:
    def test_dev_host_always_present(self):
        csp = _build_content_security_policy()
        assert "https://*.clerk.accounts.dev" in csp

    def test_production_fapi_host_is_allowlisted(self):
        with patch.object(settings, "clerk_issuer", "https://clerk.scenesentry.com"):
            csp = _build_content_security_policy()
        # Present in script-src, connect-src, and frame-src.
        assert csp.count("https://clerk.scenesentry.com") >= 3
        assert "script-src" in csp and "https://clerk.scenesentry.com" in csp.split("connect-src")[0]

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
