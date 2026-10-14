"""TVmaze updates feed with a stored bookmark (ADR-0006, issue #86).

Driven through the scheduled job (tvmaze_updates_task) with a fake feed and the in-memory
test database: no network, no real database.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.models.external_id import ContentExternalId
from app.models.sync_state import SyncState
from app.services.providers.base import ProviderError
from app.services.refresh_planner import due_titles
from tests.id_helpers import add_title as id_add_title

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class FakeFeed:
    name = "tvmaze"

    def __init__(self):
        self.changes = []  # (tvmaze_id, changed_at)
        self.asked = []
        self.fail = False

    def change(self, tvmaze_id, at):
        self.changes.append((tvmaze_id, at))

    def get_updated_ids(self, content_type, since):
        self.asked.append((content_type, since))
        if self.fail:
            raise ProviderError("tvmaze", "updates feed unavailable")
        return [i for i, at in self.changes if at >= since]


def add_title(db, title, tvmaze_id, content_type="tv_show", next_refresh_at=None):
    return id_add_title(db, title, content_type, ids={"tvmaze": tvmaze_id}, next_refresh_at=next_refresh_at)


def set_bookmark(db, bookmark):
    db.add(SyncState(provider="tvmaze", stream="tv_show", watermark=bookmark))
    db.commit()


def state(db):
    db.expire_all()
    return db.query(SyncState).filter_by(provider="tvmaze", stream="tv_show").one()


def run_job(db, feed, now=NOW):
    from app.tasks.periodic import tvmaze_updates_task

    @contextmanager
    def session():
        yield db

    with (
        patch("app.tasks.periodic.db_session", session),
        patch("app.tasks.periodic.get_tvmaze_provider", return_value=feed),
        patch("app.services.tvmaze_updates.utc_now", return_value=now),
    ):
        return tvmaze_updates_task.run()


def due_ids(db, now=NOW):
    due = {t.id for t in due_titles(db, 100, now)}
    rows = db.query(ContentExternalId).filter(ContentExternalId.content_id.in_(due)).all()
    return {int(r.external_id) for r in rows}


def test_only_changed_titles_we_already_know_are_queued_for_refresh(db_session):
    later = NOW + timedelta(days=30)
    add_title(db_session, "Changed", 1, next_refresh_at=later)
    add_title(db_session, "Quiet", 2, next_refresh_at=later)
    set_bookmark(db_session, NOW - timedelta(hours=2))
    feed = FakeFeed()
    feed.change(1, NOW - timedelta(minutes=30))
    feed.change(999, NOW - timedelta(minutes=20))  # a show we do not have

    run_job(db_session, feed)

    assert due_ids(db_session) == {1}


def test_bookmark_moves_forward_to_the_run_start_after_success(db_session):
    set_bookmark(db_session, NOW - timedelta(hours=2))

    run_job(db_session, FakeFeed())

    row = state(db_session)
    assert row.watermark.replace(tzinfo=UTC) == NOW
    assert row.status == "ok"


def test_failure_leaves_the_bookmark_alone_and_records_the_error(db_session):
    before = NOW - timedelta(hours=2)
    set_bookmark(db_session, before)
    feed = FakeFeed()
    feed.fail = True

    run_job(db_session, feed)

    row = state(db_session)
    assert row.watermark.replace(tzinfo=UTC) == before
    assert row.status == "failed"
    assert "updates feed unavailable" in row.last_error


def test_a_run_after_a_failure_picks_up_what_the_failed_run_missed(db_session):
    add_title(db_session, "Missed", 1, next_refresh_at=NOW + timedelta(days=30))
    set_bookmark(db_session, NOW - timedelta(hours=2))
    feed = FakeFeed()
    feed.change(1, NOW - timedelta(hours=1))
    feed.fail = True
    run_job(db_session, feed)
    assert due_ids(db_session) == set()

    feed.fail = False
    run_job(db_session, feed, now=NOW + timedelta(hours=1))

    assert due_ids(db_session, NOW + timedelta(hours=1)) == {1}


def test_a_gap_larger_than_the_widest_window_skips_the_feed_and_leaves_it_to_the_planner(db_session):
    set_bookmark(db_session, NOW - timedelta(days=60))
    feed = FakeFeed()

    run_job(db_session, feed)

    assert feed.asked == []
    assert state(db_session).status == "gap_fallback"


def test_ids_are_matched_within_the_same_content_type(db_session):
    add_title(db_session, "A movie", 1, content_type="movie", next_refresh_at=NOW + timedelta(days=30))
    set_bookmark(db_session, NOW - timedelta(hours=2))
    feed = FakeFeed()
    feed.change(1, NOW - timedelta(minutes=10))

    run_job(db_session, feed)

    assert due_ids(db_session) == set()


def test_job_is_a_no_op_when_tvmaze_is_not_enabled():
    from app.tasks.periodic import tvmaze_updates_task

    with patch("app.tasks.periodic.get_tvmaze_provider", return_value=None):
        assert tvmaze_updates_task.run() == {"skipped": "provider_inactive"}


class FakeHTTP:
    """Stands in for the httpx client: answers /updates/shows?since=<window> from a canned body."""

    def __init__(self, body=None, fail=False):
        self.body, self.fail, self.calls = body if body is not None else {}, fail, []

    def get(self, path, params=None):
        import httpx

        self.calls.append((path, dict(params or {})))
        if self.fail:
            raise httpx.ConnectError("down")
        request = httpx.Request("GET", "https://api.tvmaze.com" + path)
        return httpx.Response(200, json=self.body, request=request)


def provider_with_http(http):
    from collections import deque

    from app.services.providers.tvmaze_provider import TVMazeProvider

    provider = TVMazeProvider.__new__(TVMazeProvider)
    provider._client, provider._call_times = http, deque()
    return provider


def test_provider_asks_for_the_smallest_window_that_covers_the_gap():
    for age, window in [
        (timedelta(hours=3), "day"),
        (timedelta(days=2), "week"),
        (timedelta(days=10), "month"),
    ]:
        http = FakeHTTP()
        provider_with_http(http).get_updated_ids("tv_show", NOW - age, now=NOW)
        assert http.calls[0][0] == "/updates/shows"
        assert http.calls[0][1]["since"] == window, age


def test_provider_returns_only_shows_changed_since_the_bookmark():
    since = NOW - timedelta(days=2)
    body = {
        "1": int((since + timedelta(hours=1)).timestamp()),
        "2": int((since - timedelta(hours=1)).timestamp()),  # in the week window but before our bookmark
    }

    ids = provider_with_http(FakeHTTP(body)).get_updated_ids("tv_show", since, now=NOW)

    assert ids == [1]


def test_provider_raises_provider_error_when_the_feed_call_fails():
    import pytest

    with pytest.raises(ProviderError):
        provider_with_http(FakeHTTP(fail=True)).get_updated_ids("tv_show", NOW - timedelta(hours=1), now=NOW)


def test_provider_refuses_a_gap_wider_than_a_month():
    import pytest

    with pytest.raises(ProviderError):
        provider_with_http(FakeHTTP()).get_updated_ids("tv_show", NOW - timedelta(days=45), now=NOW)
