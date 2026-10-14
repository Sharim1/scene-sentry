"""Enrichment records a refresh outcome on every title it touches.

Driven through ContentDiscoveryService.enrich_sparse_content with a fake provider and
the in-memory test database: no network.
"""

from datetime import UTC, datetime, timedelta

from app.models.content import Content
from app.services.content_discovery import ContentDiscoveryService
from app.services.providers.base import NormalizedContent


class FakeDetailProvider:
    name = "tvdb"

    def __init__(self, failing_ids=()):
        self.failing_ids = set(failing_ids)

    def get_details(self, ext_id):
        if int(ext_id) in self.failing_ids:
            raise RuntimeError(f"tvdb is down for {ext_id}")
        return NormalizedContent(title="x", content_type="movie", provider="tvdb", runtime=100)

    def get_episodes(self, ext_id):
        return []


def add_movie(db_session, title, tvdb_id):
    row = Content(title=title, content_type="movie", tvdb_id=tvdb_id)
    db_session.add(row)
    db_session.commit()
    return row


_clock = [datetime(2026, 10, 1, tzinfo=UTC)]


def enrich(db_session, provider):
    # each run happens a day later, so backoff never hides a title from the next run
    _clock[0] += timedelta(days=10)
    svc = ContentDiscoveryService(db_session)
    svc.providers = [provider]
    svc.enrich_sparse_content(batch_size=10, now=_clock[0])
    db_session.expire_all()


def test_new_titles_start_with_no_refresh_history(db_session):
    row = add_movie(db_session, "Fresh", 1)

    assert row.last_refreshed_at is None
    assert row.next_refresh_at is None
    assert row.refresh_attempts == 0
    assert row.last_error is None
    assert row.refresh_locked is False


def test_a_failing_title_is_recorded_while_the_others_in_the_batch_succeed(db_session):
    good = add_movie(db_session, "Good", 1)
    bad = add_movie(db_session, "Bad", 2)
    also_good = add_movie(db_session, "Also good", 3)

    enrich(db_session, FakeDetailProvider(failing_ids={2}))

    bad = db_session.get(Content, bad.id)
    assert bad.refresh_attempts == 1
    assert "tvdb is down for 2" in bad.last_error
    assert bad.last_refreshed_at is None
    for row_id in (good.id, also_good.id):
        row = db_session.get(Content, row_id)
        assert row.last_refreshed_at is not None
        assert row.refresh_attempts == 0
        assert row.last_error is None
        assert row.runtime == 100


def test_repeated_failures_raise_the_attempt_count(db_session):
    bad = add_movie(db_session, "Bad", 2)

    enrich(db_session, FakeDetailProvider(failing_ids={2}))
    enrich(db_session, FakeDetailProvider(failing_ids={2}))

    assert db_session.get(Content, bad.id).refresh_attempts == 2


def test_a_later_success_clears_the_failure(db_session):
    bad = add_movie(db_session, "Bad", 2)
    enrich(db_session, FakeDetailProvider(failing_ids={2}))

    enrich(db_session, FakeDetailProvider())

    row = db_session.get(Content, bad.id)
    assert row.refresh_attempts == 0
    assert row.last_error is None
    assert row.last_refreshed_at is not None
