"""Every periodic task expires with its interval and has time limits under it."""

from datetime import timedelta

from app.celery_app import celery_app
from app.models.discovery_state import DiscoveryState
from app.services.content_discovery import ContentDiscoveryService
from tests.discovery_helpers import FakeProvider, item


def _entries():
    return celery_app.conf.beat_schedule.values()


def _seconds(entry):
    schedule = entry["schedule"]
    return schedule.total_seconds() if isinstance(schedule, timedelta) else float(schedule)


def test_every_beat_entry_expires_when_its_interval_elapses():
    for entry in _entries():
        assert entry["options"]["expires"] == _seconds(entry)


def test_every_periodic_task_has_limits_under_its_interval():
    for entry in _entries():
        task = celery_app.tasks[entry["task"]]
        interval = _seconds(entry)
        assert 0 < task.soft_time_limit < task.time_limit < interval


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        self.now += 10.0
        return self.now


class ManyPages(FakeProvider):
    def discover_movies(self, page=1):
        return [item(f"Movie {page}", "movie", tvdb_id=str(page))] if page <= 20 else []


def _cursor(db_session):
    db_session.expire_all()
    return db_session.query(DiscoveryState).filter_by(provider="tvdb", content_type="movie").one().last_page


def test_discovery_at_its_time_budget_saves_cursor_and_next_run_continues(db_session):
    svc = ContentDiscoveryService(db_session)
    svc.providers = [ManyPages("tvdb")]
    svc._clock = FakeClock()

    svc.run_scheduled_sync(time_budget=35)
    first = _cursor(db_session)
    assert 0 < first < 20

    svc.run_scheduled_sync(time_budget=35)
    assert _cursor(db_session) > first
