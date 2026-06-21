"""Route tests for the SCE-33 similar-content demo endpoint."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.dependencies import get_db, require_auth
from app.models.content import Content
from app.models.user import User


@pytest.fixture()
def client(db_session):
    from app.main import app

    test_user = User(id=1, username="tester", email="test@example.com")

    def override_get_db():
        yield db_session

    def override_require_auth():
        return test_user

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_auth] = override_require_auth

    with (
        patch("app.main.init_db"),
        patch("app.main.start_scheduler", create=True),
        TestClient(app, raise_server_exceptions=False) as test_client,
    ):
        yield test_client

    app.dependency_overrides.clear()


def test_unknown_content_returns_404(client: TestClient):
    resp = client.get("/api/content/99999/similar")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Content not found"


def test_content_without_embedding_returns_empty_results(client: TestClient, db_session):
    content = Content(title="Unembedded", content_type="movie")
    db_session.add(content)
    db_session.flush()

    resp = client.get(f"/api/content/{content.id}/similar")

    assert resp.status_code == 200
    body = resp.json()
    assert body["source_id"] == content.id
    assert body["results"] == []
