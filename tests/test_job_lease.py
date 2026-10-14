"""Each periodic job holds a short-lived lease so two runs never overlap."""

from unittest.mock import MagicMock, patch

import pytest

from app.celery_app import celery_app
from app.tasks import lease
from tests.lease_helpers import FakeLeaseStore


@pytest.fixture
def store():
    s = FakeLeaseStore()
    with patch.object(lease, "_store", s):
        yield s


def _run_cleanup():
    from app.tasks.periodic import cleanup_task

    db = MagicMock()
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=db)
    cm.__exit__ = MagicMock(return_value=False)
    with patch("app.tasks.periodic.db_session", MagicMock(return_value=cm)):
        result = cleanup_task.run()
    return result, db.query.called


def test_second_start_while_lease_held_does_nothing_and_says_why(store):
    assert store.acquire("cleanup_task", 600)

    result, touched_db = _run_cleanup()

    assert touched_db is False
    assert result == {"skipped": "lease_held", "job": "cleanup_task"}


def test_lease_is_released_after_a_run_so_the_next_run_proceeds(store):
    _, first = _run_cleanup()
    _, second = _run_cleanup()
    assert first and second


def test_lease_is_released_when_the_run_fails(store):
    from app.tasks.periodic import cleanup_task

    with patch("app.tasks.periodic.db_session", side_effect=RuntimeError("boom")):
        with patch.object(cleanup_task, "retry", side_effect=RuntimeError("retry")):
            with pytest.raises(RuntimeError):
                cleanup_task.run()

    assert store.acquire("cleanup_task", 10)


def test_crashed_runs_lease_expires_after_the_task_hard_limit(store):
    from app.tasks.periodic import cleanup_task

    store.acquire("cleanup_task", cleanup_task.time_limit)  # a crashed run never released it
    store.advance(cleanup_task.time_limit + 1)

    _, ran = _run_cleanup()
    assert ran


def test_every_periodic_task_is_guarded_by_the_lease():
    for entry in celery_app.conf.beat_schedule.values():
        task = celery_app.tasks[entry["task"]]
        assert getattr(task.run, "__leased__", False), entry["task"]
