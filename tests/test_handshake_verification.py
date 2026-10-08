"""The Clerk handshake token must be verified before its cookie instructions are applied.

Driven through HTTP only (TestClient + the whole middleware stack). The one stub
is Clerk's JWKS endpoint, so signature / expiry / key-id checks run for real.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from tests.clerk_helpers import ClerkSigner, clerk_jwks

SESSION_SET = "__session=attacker-session; Path=/; Max-Age=3600; Secure; SameSite=Lax"
UAT_SET = "__client_uat=1716500000; Path=/; Max-Age=3600; Secure; SameSite=Lax"


def _set_cookie_names(resp) -> list[str]:
    return [h.split("=", 1)[0] for h in resp.headers.get_list("set-cookie")]


def _applied_session(resp) -> bool:
    return any(h.startswith("__session=attacker-session") for h in resp.headers.get_list("set-cookie"))


@pytest.fixture()
def signer():
    return ClerkSigner()


@pytest.fixture()
def make_client():
    """Build a TestClient with Clerk configured, in the given environment."""

    from contextlib import ExitStack

    from app.config import settings
    from app.main import app

    stack = ExitStack()

    def _make(env: str = "development") -> TestClient:
        stack.enter_context(patch("app.main.init_db"))
        stack.enter_context(patch.object(settings, "clerk_secret_key", "sk_test_fake"))
        stack.enter_context(patch.object(settings, "clerk_publishable_key", "pk_test_fake"))
        stack.enter_context(patch.object(settings, "clerk_issuer", "https://clerk.example.com"))
        stack.enter_context(patch.object(settings, "env", env))
        return stack.enter_context(TestClient(app, raise_server_exceptions=False, base_url="https://testserver"))

    yield _make
    stack.close()


class TestHandshakeSignature:
    def test_genuinely_signed_handshake_in_cookie_is_applied(self, make_client, signer):
        client = make_client("production")
        token = signer.handshake_jwt([SESSION_SET, UAT_SET])

        with clerk_jwks(signer):
            resp = client.get("/dashboard", cookies={"__clerk_handshake": token}, follow_redirects=False)

        assert resp.status_code == 307
        assert _applied_session(resp)
        assert "__client_uat" in _set_cookie_names(resp)

    def test_handshake_signed_with_an_unknown_key_is_ignored(self, make_client, signer):
        """A token the attacker signed with their own key must not plant a session."""
        client = make_client("production")
        forger = ClerkSigner()
        token = forger.handshake_jwt([SESSION_SET], kid=signer.kid)  # claims the trusted kid

        with clerk_jwks(signer):
            resp = client.get("/dashboard", cookies={"__clerk_handshake": token}, follow_redirects=False)

        assert not _applied_session(resp)

    def test_unsigned_handshake_is_ignored(self, make_client, signer):
        client = make_client("production")
        import base64
        import json

        def b64(d: dict) -> str:
            return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()

        token = f"{b64({'alg': 'none', 'typ': 'JWT'})}.{b64({'handshake': [SESSION_SET]})}.sig"

        with clerk_jwks(signer):
            resp = client.get("/dashboard", cookies={"__clerk_handshake": token}, follow_redirects=False)

        assert not _applied_session(resp)

    def test_expired_handshake_is_ignored(self, make_client, signer):
        client = make_client("production")
        token = signer.handshake_jwt([SESSION_SET], expires_in=-3600)

        with clerk_jwks(signer):
            resp = client.get("/dashboard", cookies={"__clerk_handshake": token}, follow_redirects=False)

        assert not _applied_session(resp)

    def test_rejected_handshake_does_not_break_the_page_flow(self, make_client, signer):
        """A bad token must degrade to normal handling (no 5xx, no loop)."""
        client = make_client("production")
        token = ClerkSigner().handshake_jwt([SESSION_SET], kid=signer.kid)

        with clerk_jwks(signer):
            resp = client.get("/dashboard", cookies={"__clerk_handshake": token}, follow_redirects=False)

        assert resp.status_code in (303, 307)
        assert resp.status_code < 500


class TestHandshakeTokenCategory:
    """Clerk tags each JWT class in its header. A validly signed token of another
    class (e.g. a custom JWT template, which can carry an arbitrary `handshake`
    claim) must not be accepted as a handshake. Mirrors Clerk's own backend SDK."""

    SESSION_CAT = "cl_B7d4PD111AAA"
    TEMPLATE_CAT = "cl_B7d4PD222AAA"
    IGNORE_CAT = "cl_I7d4PD111III"

    def test_jwt_template_token_is_not_accepted_as_a_handshake(self, make_client, signer):
        client = make_client("production")
        token = signer.handshake_jwt([SESSION_SET], cat=self.TEMPLATE_CAT)

        with clerk_jwks(signer):
            resp = client.get("/dashboard", cookies={"__clerk_handshake": token}, follow_redirects=False)

        assert not _applied_session(resp)

    @pytest.mark.parametrize("cat", [None, SESSION_CAT, IGNORE_CAT])
    def test_session_category_ignore_marker_or_absent_category_is_accepted(self, make_client, signer, cat):
        client = make_client("production")
        token = signer.handshake_jwt([SESSION_SET], cat=cat)

        with clerk_jwks(signer):
            resp = client.get("/dashboard", cookies={"__clerk_handshake": token}, follow_redirects=False)

        assert _applied_session(resp)


class TestHandshakeDelivery:
    def test_query_param_handshake_is_ignored_in_production(self, make_client, signer):
        """A link carrying a (even validly signed) handshake must not set cookies
        in production: Clerk delivers it via cookie there, and a link can't set
        another user's cookie."""
        client = make_client("production")
        token = signer.handshake_jwt([SESSION_SET])

        with clerk_jwks(signer):
            resp = client.get(f"/dashboard?__clerk_handshake={token}", follow_redirects=False)

        assert not _applied_session(resp)

    def test_query_param_handshake_still_works_outside_production(self, make_client, signer):
        """Clerk Development instances can't set cross-site cookies, so they
        deliver the handshake as a query parameter; local development relies on it."""
        client = make_client("development")
        token = signer.handshake_jwt([SESSION_SET])

        with clerk_jwks(signer):
            resp = client.get(f"/dashboard?__clerk_handshake={token}", follow_redirects=False)

        assert resp.status_code == 307
        assert _applied_session(resp)
        assert "__clerk_handshake" not in resp.headers["location"]

    def test_unsigned_query_param_is_ignored_even_in_development(self, make_client, signer):
        client = make_client("development")
        forged = ClerkSigner().handshake_jwt([SESSION_SET], kid=signer.kid)

        with clerk_jwks(signer):
            resp = client.get(f"/dashboard?__clerk_handshake={forged}", follow_redirects=False)

        assert not _applied_session(resp)


class TestHandshakeCookieInstructions:
    def test_cookies_outside_the_allow_list_are_never_set(self, make_client, signer):
        client = make_client("production")
        token = signer.handshake_jwt([SESSION_SET, "evil=1; Path=/", "session=abc; Path=/"])

        with clerk_jwks(signer):
            resp = client.get("/dashboard", cookies={"__clerk_handshake": token}, follow_redirects=False)

        names = _set_cookie_names(resp)
        assert "evil" not in names
        assert "session" not in names
        assert _applied_session(resp)

    def test_cookie_scoped_to_a_foreign_domain_is_not_set(self, make_client, signer):
        client = make_client("production")
        token = signer.handshake_jwt(["__session=attacker-session; Path=/; Domain=evil.example; Secure"])

        with clerk_jwks(signer):
            resp = client.get("/dashboard", cookies={"__clerk_handshake": token}, follow_redirects=False)

        assert not _applied_session(resp)

    def test_cookie_scoped_to_a_parent_of_the_request_host_is_allowed(self, make_client, signer):
        """Clerk really does send Domain=<apex> (the logout fix depends on it)."""
        client = make_client("production")
        token = signer.handshake_jwt(["__session=attacker-session; Path=/; Domain=testserver; Secure"])

        with clerk_jwks(signer):
            resp = client.get("/dashboard", cookies={"__clerk_handshake": token}, follow_redirects=False)

        assert _applied_session(resp)

    def test_handshake_cookie_is_cleared_after_use(self, make_client, signer):
        client = make_client("production")
        token = signer.handshake_jwt([SESSION_SET])

        with clerk_jwks(signer):
            resp = client.get("/dashboard", cookies={"__clerk_handshake": token}, follow_redirects=False)

        cleared = [h for h in resp.headers.get_list("set-cookie") if h.startswith("__clerk_handshake=")]
        assert cleared, "the consumed handshake cookie must be cleared"

    def test_signed_out_instruction_is_still_applied(self, make_client, signer):
        """Clerk's explicit __client_uat=0 'signed out' signal must keep working (redirect-loop guard)."""
        client = make_client("production")
        token = signer.handshake_jwt(
            [
                "__client_uat=0; Path=/; Max-Age=315360000; Secure; SameSite=Lax",
                "__session=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Secure; SameSite=Lax",
            ]
        )

        with clerk_jwks(signer):
            resp = client.get(
                "/dashboard",
                cookies={"__client_uat": "1716500000", "__clerk_handshake": token},
                follow_redirects=False,
            )

        assert any("__client_uat=0" in h for h in resp.headers.get_list("set-cookie"))
