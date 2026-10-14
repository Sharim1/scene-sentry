"""Tier planner: enrichment picks titles by refresh tier, never by id order.

Driven through ContentDiscoveryService.enrich_sparse_content with a fake provider and
the in-memory test database: no network.
"""

from datetime import UTC, datetime, timedelta

from app.config import settings
from app.models.content import Content
from app.models.library import LibraryItem
from app.models.user import User
from app.services.content_discovery import ContentDiscoveryService
from app.services.providers.base import NormalizedContent
from app.services.refresh_planner import failing_titles
from tests.id_helpers import add_title

NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


class RecordingProvider:
    name = "tvdb"

    def __init__(self, failing_ids=()):
        self.failing_ids = set(failing_ids)
        self.asked = []

    def get_details(self, ext_id):
        self.asked.append(int(ext_id))
        if int(ext_id) in self.failing_ids:
            raise RuntimeError("down")
        return NormalizedContent(title="x", content_type="movie", provider="tvdb", runtime=100)

    def get_episodes(self, ext_id):
        return []


def add(db, tvdb_id, content_type="movie", **kw):
    return add_title(db, f"t{tvdb_id}", content_type, ids={"tvdb": tvdb_id}, **kw)


def run(db, provider, batch=10, now=NOW):
    svc = ContentDiscoveryService(db)
    svc.providers = [provider]
    svc.enrich_sparse_content(batch_size=batch, now=now)
    db.expire_all()
    return provider.asked


def aware(dt):
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def test_failing_title_is_not_picked_again_until_backoff_passes(db_session):
    add(db_session, 1)
    p = RecordingProvider(failing_ids={1})
    run(db_session, p)
    run(db_session, p, now=NOW + timedelta(minutes=1))
    assert p.asked == [1]

    run(db_session, p, now=NOW + timedelta(hours=settings.refresh_failure_backoff_base_hours, minutes=1))
    assert p.asked == [1, 1]


def test_backoff_doubles_and_is_capped_at_a_week(db_session):
    row = add(db_session, 1)
    p = RecordingProvider(failing_ids={1})
    now = NOW
    gaps = []
    for _ in range(12):
        run(db_session, p, now=now)
        row = db_session.get(Content, row.id)
        gap = aware(row.next_refresh_at) - now
        gaps.append(gap)
        now = aware(row.next_refresh_at)
    assert gaps[1] == gaps[0] * 2
    assert max(gaps) == timedelta(days=settings.refresh_failure_backoff_cap_days) == timedelta(days=7)


def test_tiers_run_hot_then_warm_then_cold(db_session):
    add(db_session, 1, "tv_show", status="Ended")
    add(db_session, 2, "tv_show", status="Continuing")
    add(db_session, 3, "tv_show", status="Ended", next_episode_date=NOW + timedelta(days=3))
    p = RecordingProvider()
    run(db_session, p)
    assert p.asked == [3, 2, 1]


def test_title_tracked_by_a_user_is_hot(db_session):
    add(db_session, 1, "tv_show", status="Continuing")
    tracked = add(db_session, 2, "tv_show", status="Ended")
    user = User(username="u", email="u@example.com")
    db_session.add(user)
    db_session.commit()
    db_session.add(LibraryItem(user_id=user.id, content_id=tracked.id))
    db_session.commit()
    p = RecordingProvider()
    run(db_session, p)
    assert p.asked[0] == 2


def test_airing_beyond_fourteen_days_is_not_hot(db_session):
    add(db_session, 1, "tv_show", status="Continuing")
    add(db_session, 2, "tv_show", status="Ended", next_episode_date=NOW + timedelta(days=30))
    p = RecordingProvider()
    run(db_session, p)
    assert p.asked == [1, 2]


def test_never_refreshed_beats_a_due_refreshed_title_in_same_tier(db_session):
    a = add(db_session, 1, status="Ended")
    add(db_session, 2, status="Ended")
    a.last_refreshed_at = NOW - timedelta(days=400)
    a.next_refresh_at = NOW - timedelta(days=1)
    db_session.commit()
    p = RecordingProvider()
    run(db_session, p, batch=1)
    assert p.asked == [2]


def test_success_schedules_next_refresh_by_tier(db_session):
    row = add(db_session, 1, status="Ended")
    run(db_session, RecordingProvider())
    row = db_session.get(Content, row.id)
    assert aware(row.next_refresh_at) == NOW + timedelta(days=settings.refresh_cold_days)


def test_tier_lengths_are_settings_with_adr_starting_values():
    assert settings.refresh_hot_hours == 6
    assert settings.refresh_warm_hours == 12
    assert settings.refresh_cold_days == 30
    assert settings.refresh_failure_backoff_cap_days == 7
    assert settings.refresh_airing_window_days == 14
    assert settings.refresh_failure_threshold == 3


def test_report_lists_titles_with_three_or_more_failures(db_session):
    add(db_session, 1)
    add(db_session, 2)
    p = RecordingProvider(failing_ids={1})
    now = NOW
    for _ in range(3):
        run(db_session, p, now=now)
        now += timedelta(days=8)
    report = failing_titles(db_session)
    assert [r.title for r in report] == ["t1"]
    assert report[0].refresh_attempts == 3
    assert "down" in report[0].last_error


def test_cold_delay_is_a_setting_capped_at_the_adr_ceiling(db_session, monkeypatch):
    from app.services.refresh_planner import success_delay

    row = add(db_session, 1, status="Ended")
    monkeypatch.setattr(settings, "refresh_cold_days", 90)
    assert success_delay(db_session, row.id, NOW) == timedelta(days=90)

    monkeypatch.setattr(settings, "refresh_cold_days", 365)
    assert success_delay(db_session, row.id, NOW) == timedelta(days=settings.refresh_cold_days_max)
    assert settings.refresh_cold_days_max == 180
