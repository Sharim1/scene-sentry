"""Smoke tests for the health endpoint and app startup."""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    """TestClient that skips the real lifespan (no DB / scheduler needed)."""
    from app.main import app

    with (
        patch("app.main.init_db"),
        patch("app.main.start_scheduler", create=True),
        TestClient(app, raise_server_exceptions=False) as c,
    ):
        yield c


def test_health_returns_200(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert "version" in body


def test_favicon_does_not_500(client: TestClient):
    resp = client.get("/favicon.ico")
    assert resp.status_code in (200, 204)
