"""TVDB updates feed with a stored bookmark (ADR-0006, issue #84).

Driven through the scheduled job (tvdb_updates_task) with a fake feed and the in-memory
test database: no network, no real database.
"""

from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.models.content import Content
from app.models.external_id import ContentExternalId
from app.models.sync_state import SyncState
from app.services.provider_notices import Notice
from app.services.providers.base import ProviderError
from app.services.refresh_planner import due_titles

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class FakeFeed:
    """A TVDB stand-in whose updates feed honours ``since`` like the real one."""

    name = "tvdb"

    def __init__(self):
        self.changes = {"tv_show": [], "movie": []}  # (tvdb_id, changed_at)
        self.notices = {"tv_show": [], "movie": []}  # (Notice, changed_at)
        self.asked = []
        self.fail = False

    def change(self, content_type, tvdb_id, at):
        self.changes[content_type].append((tvdb_id, at))

    def get_updated_ids(self, content_type, since):
        self.asked.append((content_type, since))
        if self.fail:
            raise ProviderError("tvdb", "updates feed unavailable")
        return [i for i, at in self.changes[content_type] if at >= since]

    def read_updates(self, content_type, since):
        notices = [n for n, at in self.notices[content_type] if at >= since]
        return self.get_updated_ids(content_type, since), notices

    def notice(self, content_type, notice, at):
        self.notices[content_type].append((notice, at))


def add_title(db, title, tvdb_id, content_type="tv_show", next_refresh_at=None):
    # The id lives only in the external-id table: the old column must not be what is read.
    row = Content(title=title, content_type=content_type, next_refresh_at=next_refresh_at)
    db.add(row)
    db.flush()
    db.add(ContentExternalId(provider="tvdb", kind=content_type, external_id=str(tvdb_id), content_id=row.id))
    db.commit()
    return row


def set_bookmark(db, bookmark, stream="tv_show"):
    db.add(SyncState(provider="tvdb", stream=stream, watermark=bookmark))
    db.commit()


def state(db, stream="tv_show"):
    db.expire_all()
    return db.query(SyncState).filter_by(provider="tvdb", stream=stream).one()


def run_job(db, feed, now=NOW):
    from app.tasks.periodic import tvdb_updates_task

    @contextmanager
    def session():
        yield db

    with (
        patch("app.tasks.periodic.db_session", session),
        patch("app.tasks.periodic.get_tvdb_provider", return_value=feed),
        patch("app.services.tvdb_updates.utc_now", return_value=now),
    ):
        return tvdb_updates_task.run()


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
    feed.change("tv_show", 1, NOW - timedelta(minutes=30))
    feed.change("tv_show", 999, NOW - timedelta(minutes=20))  # a title we do not have

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
    feed.change("tv_show", 1, NOW - timedelta(hours=1))
    feed.fail = True
    run_job(db_session, feed)
    assert due_ids(db_session) == set()

    feed.fail = False
    run_job(db_session, feed, now=NOW + timedelta(hours=1))

    assert due_ids(db_session, NOW + timedelta(hours=1)) == {1}
    assert state(db_session).status == "ok"


def test_overlap_catches_an_update_stamped_just_before_the_bookmark(db_session):
    add_title(db_session, "Boundary", 1, next_refresh_at=NOW + timedelta(days=30))
    bookmark = NOW - timedelta(hours=1)
    set_bookmark(db_session, bookmark)
    feed = FakeFeed()
    feed.change("tv_show", 1, bookmark - timedelta(minutes=5))  # landed late, stamped before the bookmark

    run_job(db_session, feed)

    assert due_ids(db_session) == {1}


def test_a_gap_larger_than_the_feed_window_skips_the_feed_and_leaves_it_to_the_planner(db_session):
    add_title(db_session, "Stale", 1, next_refresh_at=NOW + timedelta(days=30))
    set_bookmark(db_session, NOW - timedelta(days=60))
    feed = FakeFeed()
    feed.change("tv_show", 1, NOW - timedelta(days=1))

    run_job(db_session, feed)

    assert feed.asked == []
    assert due_ids(db_session) == set()
    row = state(db_session)
    assert row.status == "gap_fallback"
    assert row.watermark.replace(tzinfo=UTC) == NOW


def test_streams_are_independent_a_movie_failure_does_not_block_shows(db_session):
    add_title(db_session, "Show", 1, next_refresh_at=NOW + timedelta(days=30))
    set_bookmark(db_session, NOW - timedelta(hours=2), "tv_show")
    set_bookmark(db_session, NOW - timedelta(hours=2), "movie")

    class MoviesDown(FakeFeed):
        def get_updated_ids(self, content_type, since):
            if content_type == "movie":
                raise ProviderError("tvdb", "movies down")
            return super().get_updated_ids(content_type, since)

    feed = MoviesDown()
    feed.change("tv_show", 1, NOW - timedelta(minutes=10))

    run_job(db_session, feed)

    assert state(db_session, "tv_show").status == "ok"
    assert state(db_session, "movie").status == "failed"
    assert due_ids(db_session) == {1}


def test_ids_are_matched_within_the_same_content_type(db_session):
    add_title(db_session, "A movie", 1, content_type="movie", next_refresh_at=NOW + timedelta(days=30))
    set_bookmark(db_session, NOW - timedelta(hours=2))
    feed = FakeFeed()
    feed.change("tv_show", 1, NOW - timedelta(minutes=10))  # a series with the same number

    run_job(db_session, feed)

    assert due_ids(db_session) == set()


def test_delete_and_merge_notices_from_the_feed_are_applied_and_the_bookmark_moves(db_session):
    from app.models.library import LibraryItem
    from app.models.user import User

    gone = add_title(db_session, "Gone", 1)
    old = add_title(db_session, "Old", 2)
    survivor = add_title(db_session, "Survivor", 3)
    user = User(username="u", email="u@example.com")
    db_session.add(user)
    db_session.flush()
    item = LibraryItem(user_id=user.id, content_id=old.id)
    db_session.add(item)
    db_session.commit()
    survivor_id, item_id, gone_id = survivor.id, item.id, gone.id
    set_bookmark(db_session, NOW - timedelta(hours=2))
    feed = FakeFeed()
    at = NOW - timedelta(minutes=10)
    feed.notice("tv_show", Notice("delete", "tvdb", "tv_show", "1"), at)
    feed.notice("tv_show", Notice("merge", "tvdb", "tv_show", "2", "3"), at)

    run_job(db_session, feed)

    db_session.expire_all()
    assert db_session.get(Content, gone_id) is None
    assert db_session.get(LibraryItem, item_id).content_id == survivor_id
    assert state(db_session).watermark.replace(tzinfo=UTC) == NOW


def test_first_run_starts_the_bookmark_without_fetching(db_session):
    feed = FakeFeed()

    run_job(db_session, feed)

    assert feed.asked == []
    assert state(db_session).watermark.replace(tzinfo=UTC) == NOW


def test_job_is_a_no_op_when_tvdb_is_not_configured():
    from app.tasks.periodic import tvdb_updates_task

    with patch("app.tasks.periodic.get_tvdb_provider", return_value=None):
        assert tvdb_updates_task.run() == {"skipped": "provider_inactive"}


class FakeSDKClient:
    """Stands in for tvdb_v4_official.TVDB: pages of update records."""

    def __init__(self, pages, fail=False):
        self.pages, self.fail, self.calls = pages, fail, []

    def get_updates(self, since, **kwargs):
        self.calls.append((since, kwargs))
        if self.fail:
            raise RuntimeError("boom")
        return self.pages.get(kwargs.get("page", 0), [])


def provider_with_client(client):
    from app.services.providers.tvdb_provider import TVDBProvider

    provider = TVDBProvider.__new__(TVDBProvider)
    provider.client = client
    return provider


def test_provider_reads_every_page_of_the_feed_and_skips_deletions():
    pages = {
        0: [{"recordId": 1, "method": "update"}, {"recordId": 2, "method": "delete"}],
        1: [{"recordId": 3, "method": "create"}],
    }
    client = FakeSDKClient(pages)

    ids = provider_with_client(client).get_updated_ids("tv_show", NOW)

    assert sorted(ids) == [1, 3]
    since, kwargs = client.calls[0]
    assert since == int(NOW.timestamp())
    assert kwargs["type"] == "series"


def test_provider_turns_delete_and_merge_records_into_notices_in_the_same_pass():
    # Record shape assumed from TVDB v4 /updates: method "delete", with mergeToId when merged.
    pages = {
        0: [
            {"recordId": 1, "method": "update"},
            {"recordId": 2, "method": "delete"},
            {"recordId": 3, "method": "delete", "mergeToId": 4, "mergeToEntityType": "series"},
        ],
    }
    client = FakeSDKClient(pages)

    ids, notices = provider_with_client(client).read_updates("tv_show", NOW)

    assert ids == [1]
    assert notices == [
        Notice(action="delete", provider="tvdb", content_type="tv_show", external_id="2"),
        Notice(action="merge", provider="tvdb", content_type="tv_show", external_id="3", merged_into="4"),
    ]
    assert len(client.calls) == 2  # page 0, then the empty page that ends the feed


def test_provider_raises_provider_error_when_the_feed_call_fails():
    import pytest

    with pytest.raises(ProviderError):
        provider_with_client(FakeSDKClient({}, fail=True)).get_updated_ids("movie", NOW)


def test_soft_time_limit_ends_the_run_cleanly_and_keeps_the_bookmark(db_session):
    from celery.exceptions import SoftTimeLimitExceeded

    before = NOW - timedelta(hours=2)
    set_bookmark(db_session, before)

    class OutOfTime(FakeFeed):
        def read_updates(self, content_type, since):
            raise SoftTimeLimitExceeded()

    run_job(db_session, OutOfTime())  # must not raise (no retry)

    row = state(db_session)
    assert row.watermark.replace(tzinfo=UTC) == before
    assert row.status == "timeout"


def test_a_notice_that_fails_does_not_hold_the_bookmark_back(db_session):
    set_bookmark(db_session, NOW - timedelta(hours=2))
    add_title(db_session, "Doomed", 1)
    feed = FakeFeed()
    feed.notice("tv_show", Notice("delete", "tvdb", "tv_show", "1"), NOW - timedelta(minutes=10))

    with patch("app.services.provider_notices._apply_delete", side_effect=RuntimeError("boom")):
        run_job(db_session, feed)

    row = state(db_session)
    assert row.watermark.replace(tzinfo=UTC) == NOW
    assert row.status == "ok"
    assert "1 notice(s) failed" in row.last_error
