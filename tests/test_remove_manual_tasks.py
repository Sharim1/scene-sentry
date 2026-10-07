"""Verify that manual task endpoints and the refresh route are removed.

These tests exist to confirm the Task system (user-triggered background jobs
with SSE progress) has been fully removed in favor of Celery Beat scheduled
jobs. See ADR-0001.
"""

from unittest.mock import patch

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


class TestGossipFeedStillWorks:
    def test_gossip_feed_redirects_to_login_for_unauthenticated(self, client: TestClient):
        resp = client.get("/gossip", follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers["location"] == "/login?next=/gossip"


class TestRemovedEndpoints:
    def test_gossip_refresh_not_routable(self, client: TestClient):
        resp = client.post("/gossip/refresh", follow_redirects=False)
        assert resp.status_code in (404, 405)

    def test_task_start_not_routable(self, client: TestClient):
        resp = client.post("/api/tasks/gossip_scrape/start")
        assert resp.status_code in (404, 405)

    def test_task_list_not_routable(self, client: TestClient):
        resp = client.get("/api/tasks")
        assert resp.status_code == 404

    def test_task_stream_not_routable(self, client: TestClient):
        resp = client.get("/api/tasks/stream")
        assert resp.status_code == 404

    def test_task_cancel_not_routable(self, client: TestClient):
        resp = client.post("/api/tasks/some-id/cancel")
        assert resp.status_code in (404, 405)
