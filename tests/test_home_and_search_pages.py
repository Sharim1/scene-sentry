"""The redesigned Home page and the unified /search page actually render.

No existing test exercised /dashboard or /search with real Jinja rendering —
passing unit tests don't catch a template error, only a request does.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_current_user, get_db
from app.models.content import Content
from app.models.user import User


@pytest.fixture()
def seeded_content(db_session):
    rows = [
        Content(title="New Release", content_type="movie", release_date="2026-10-01", rating=7.5, genres='["Action"]'),
        Content(
            title="Old Favorite", content_type="tv_show", release_date="2001-01-01", rating=9.2, genres='["Drama"]'
        ),
        Content(title="Future Film", content_type="movie", release_date="2099-01-01"),
    ]
    db_session.add_all(rows)
    db_session.commit()
    return rows


@pytest.fixture()
def client(db_session):
    from app.main import app

    test_user = User(id=1, username="tester", email="test@example.com")
    db_session.add(test_user)
    db_session.commit()

    def override_get_db():
        yield db_session

    def override_get_current_user():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = override_get_current_user

    with (
        patch("app.main.init_db"),
        patch("app.main.start_scheduler", create=True),
        TestClient(app, raise_server_exceptions=True) as c,
    ):
        yield c

    app.dependency_overrides.clear()


def test_home_renders_with_content(client: TestClient, seeded_content):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "New Release" in resp.text
    assert "Old Favorite" in resp.text
    # The nav no longer has standalone Movies / TV Shows links.
    assert 'href="/movies"' not in resp.text
    assert 'href="/tv-shows"' not in resp.text
    assert 'href="/search"' in resp.text


def test_home_renders_with_empty_catalog(client: TestClient):
    resp = client.get("/dashboard")
    assert resp.status_code == 200
    assert "still filling in" in resp.text


def test_search_page_renders_with_query(client: TestClient, seeded_content):
    resp = client.get("/search", params={"q": "New"})
    assert resp.status_code == 200
    assert "New Release" in resp.text
    assert "Old Favorite" not in resp.text


def test_search_page_filters_by_genre(client: TestClient, seeded_content):
    resp = client.get("/search", params={"genre": "Drama"})
    assert resp.status_code == 200
    assert "Old Favorite" in resp.text
    assert "New Release" not in resp.text


def test_search_page_renders_with_no_results(client: TestClient):
    resp = client.get("/search", params={"q": "nothing matches this"})
    assert resp.status_code == 200
    assert "No results found" in resp.text


def test_old_routes_are_gone(client: TestClient):
    # No dedicated route for either path anymore. They fall through to the
    # /{content_id} detail route, which 422s on a non-numeric id rather than
    # ever rendering a movies/TV-shows listing.
    assert client.get("/movies").status_code == 422
    assert client.get("/tv-shows").status_code == 422
