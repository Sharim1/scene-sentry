"""A Clerk sign-in may only be linked to a pre-existing local account when Clerk
has verified the email address.

Driven through HTTP only (TestClient + the whole middleware stack, real test DB
session). The only stubs are Clerk's network boundary: session-token
verification and the Clerk users API.
"""

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.user import User

CLERK_ID = "user_clerk_new"
COOKIES = {"__session": "stub-session-token", "__client_uat": "1716500000"}


@contextmanager
def fake_clerk_users_api(address: str | None = None, *, verified: bool = True, fail: bool = False):
    """Stub Clerk's Backend users API. Yields a counter of calls made."""
    state = SimpleNamespace(calls=0)

    class _Users:
        def get(self, user_id: str):
            state.calls += 1
            if fail:
                raise RuntimeError("clerk api down")
            if address is None:
                return SimpleNamespace(email_addresses=[], primary_email_address_id=None)
            email = SimpleNamespace(
                id="idn_1",
                email_address=address,
                verification=SimpleNamespace(status="verified" if verified else "unverified"),
            )
            return SimpleNamespace(email_addresses=[email], primary_email_address_id="idn_1")

    class _Clerk:
        def __init__(self, *a, **kw):
            self.users = _Users()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch("clerk_backend_api.Clerk", _Clerk):
        yield state


@pytest.fixture()
def client(db_session):
    from app.config import settings
    from app.dependencies import get_db
    from app.main import app

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with ExitStack() as stack:
        stack.enter_context(patch("app.main.init_db"))
        stack.enter_context(patch("app.middleware.clerk.get_db", override_get_db))
        stack.enter_context(patch.object(settings, "clerk_secret_key", "sk_test_fake"))
        stack.enter_context(patch.object(settings, "clerk_publishable_key", "pk_test_fake"))
        stack.enter_context(patch.object(settings, "clerk_issuer", "https://clerk.example.com"))
        yield stack.enter_context(TestClient(app, raise_server_exceptions=False))
    app.dependency_overrides.clear()


@pytest.fixture()
def legacy_user(db_session):
    """A local account that pre-dates Clerk (no clerk_id)."""
    user = User(username="legacy_lee", email="lee@example.com")
    db_session.add(user)
    db_session.commit()
    return user.id


def signed_in_as(claims: dict):
    return patch(
        "app.middleware.clerk.verify_clerk_token",
        new_callable=AsyncMock,
        return_value={"sub": CLERK_ID, **claims},
    )


def _user(db_session, user_id: int) -> User:
    db_session.expire_all()
    return db_session.get(User, user_id)


def _user_count(db_session) -> int:
    db_session.expire_all()
    return db_session.query(User).count()


class TestLinkingByEmail:
    def test_verified_email_links_the_legacy_account(self, client, db_session, legacy_user):
        with signed_in_as({"email": "lee@example.com"}), fake_clerk_users_api("lee@example.com", verified=True):
            resp = client.get("/dashboard", cookies=COOKIES, follow_redirects=False)

        assert resp.status_code == 200
        linked = _user(db_session, legacy_user)
        assert linked.clerk_id == CLERK_ID
        assert linked.username == "legacy_lee"
        assert _user_count(db_session) == 1

    def test_unverified_email_is_refused_and_the_legacy_account_is_untouched(self, client, db_session, legacy_user):
        with signed_in_as({"email": "lee@example.com"}), fake_clerk_users_api("lee@example.com", verified=False):
            resp = client.get("/dashboard", cookies=COOKIES, follow_redirects=False)

        assert resp.status_code == 303  # treated as signed out
        assert _user(db_session, legacy_user).clerk_id is None
        assert _user_count(db_session) == 1  # and no second account was created

    def test_refusal_explains_itself_instead_of_redirect_looping(self, client, db_session, legacy_user):
        """Sending the user to /login would bounce them straight back (Clerk sees
        them as signed in), so /login must show the reason, not redirect."""
        with signed_in_as({"email": "lee@example.com"}), fake_clerk_users_api("lee@example.com", verified=False):
            resp = client.get("/login?next=/dashboard", cookies=COOKIES, follow_redirects=False)

        assert resp.status_code == 403
        assert "verify" in resp.text.lower()
        assert "lee@example.com" not in resp.text  # don't echo the address back

    def test_email_resolved_via_backend_api_must_also_be_verified(self, client, db_session, legacy_user):
        """The token has no email claim, so the address comes from the Backend API."""
        with signed_in_as({}), fake_clerk_users_api("lee@example.com", verified=False):
            resp = client.get("/dashboard", cookies=COOKIES, follow_redirects=False)

        assert resp.status_code == 303
        assert _user(db_session, legacy_user).clerk_id is None

    def test_email_resolved_via_backend_api_links_when_verified(self, client, db_session, legacy_user):
        with signed_in_as({}), fake_clerk_users_api("lee@example.com", verified=True):
            resp = client.get("/dashboard", cookies=COOKIES, follow_redirects=False)

        assert resp.status_code == 200
        assert _user(db_session, legacy_user).clerk_id == CLERK_ID

    def test_unconfirmable_email_fails_closed(self, client, db_session, legacy_user):
        """If Clerk can't be asked, we must not assume the email is verified."""
        with signed_in_as({"email": "lee@example.com"}), fake_clerk_users_api(fail=True):
            resp = client.get("/dashboard", cookies=COOKIES, follow_redirects=False)

        assert resp.status_code == 303
        assert _user(db_session, legacy_user).clerk_id is None

    def test_token_email_is_not_trusted_over_clerks_verified_primary(self, client, db_session, legacy_user):
        """Token claims lee@; Clerk's verified primary is someone else's address."""
        with signed_in_as({"email": "lee@example.com"}), fake_clerk_users_api("other@example.com", verified=True):
            resp = client.get("/dashboard", cookies=COOKIES, follow_redirects=False)

        assert resp.status_code == 303
        assert _user(db_session, legacy_user).clerk_id is None

    def test_account_already_linked_to_another_clerk_identity_is_never_relinked(self, client, db_session):
        owner = User(username="owner", email="owner@example.com", clerk_id="user_someone_else")
        db_session.add(owner)
        db_session.commit()
        owner_id = owner.id

        with signed_in_as({"email": "owner@example.com"}), fake_clerk_users_api("owner@example.com", verified=True):
            resp = client.get("/dashboard", cookies=COOKIES, follow_redirects=False)

        assert resp.status_code == 303
        assert _user(db_session, owner_id).clerk_id == "user_someone_else"


class TestUnaffectedFlows:
    def test_brand_new_user_is_created_as_before(self, client, db_session):
        with signed_in_as({"email": "new@example.com"}), fake_clerk_users_api("new@example.com", verified=True):
            resp = client.get("/dashboard", cookies=COOKIES, follow_redirects=False)

        assert resp.status_code == 200
        created = db_session.query(User).filter(User.clerk_id == CLERK_ID).one()
        assert created.email == "new@example.com"

    def test_returning_user_signs_in_without_any_clerk_api_call(self, client, db_session):
        returning = User(username="returning", email="ret@example.com", clerk_id=CLERK_ID)
        db_session.add(returning)
        db_session.commit()

        with signed_in_as({"email": "ret@example.com"}), fake_clerk_users_api("ret@example.com") as api:
            resp = client.get("/dashboard", cookies=COOKIES, follow_redirects=False)

        assert resp.status_code == 200
        assert api.calls == 0
