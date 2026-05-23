"""Tests for the Redis-backed TaskManager."""

import asyncio

import fakeredis
import pytest

from app.services.task_manager import TaskManager, TaskStatus, TaskType


@pytest.fixture()
def manager():
    redis = fakeredis.FakeAsyncRedis()
    return TaskManager(redis)


# ── create_task ─────────────────────────────────────────────────────────


class TestCreateTask:
    async def test_returns_pending_task_with_correct_fields(self, manager):
        task = await manager.create_task(TaskType.GOSSIP_SCRAPE, user_id=1)

        assert task.id
        assert task.type == TaskType.GOSSIP_SCRAPE
        assert task.user_id == 1
        assert task.status == TaskStatus.PENDING
        assert task.progress == 0
        assert task.name == "Scanning for Gossip"

    async def test_task_is_retrievable_after_creation(self, manager):
        task = await manager.create_task(TaskType.CONTENT_RERANKING, user_id=1)

        retrieved = await manager.get_task(task.id)
        assert retrieved is not None
        assert retrieved.id == task.id
        assert retrieved.type == TaskType.CONTENT_RERANKING
        assert retrieved.status == TaskStatus.PENDING


# ── update_task ─────────────────────────────────────────────────────────


class TestUpdateTask:
    async def test_changes_only_specified_fields(self, manager):
        task = await manager.create_task(TaskType.GOSSIP_SCRAPE, user_id=1)

        await manager.update_task(task.id, progress=50)

        updated = await manager.get_task(task.id)
        assert updated.progress == 50
        assert updated.name == task.name
        assert updated.status == TaskStatus.PENDING

    async def test_running_status_sets_started_at(self, manager):
        task = await manager.create_task(TaskType.GOSSIP_SCRAPE, user_id=1)

        await manager.update_task(task.id, status=TaskStatus.RUNNING)

        updated = await manager.get_task(task.id)
        assert updated.status == TaskStatus.RUNNING
        assert updated.started_at is not None

    async def test_returns_none_for_unknown_task(self, manager):
        result = await manager.update_task("nonexistent", status=TaskStatus.RUNNING)
        assert result is None


# ── get_user_tasks ──────────────────────────────────────────────────────


class TestGetUserTasks:
    async def test_returns_only_tasks_for_specified_user(self, manager):
        await manager.create_task(TaskType.GOSSIP_SCRAPE, user_id=1)
        await manager.create_task(TaskType.GOSSIP_SCRAPE, user_id=2)

        tasks = await manager.get_user_tasks(1, active_only=False)
        assert len(tasks) == 1
        assert tasks[0].user_id == 1

    async def test_active_only_excludes_completed_tasks(self, manager):
        task = await manager.create_task(TaskType.GOSSIP_SCRAPE, user_id=1)
        await manager.update_task(task.id, status=TaskStatus.COMPLETED)

        tasks = await manager.get_user_tasks(1, active_only=True, include_recent_completed=False)
        assert len(tasks) == 0


# ── cancel_task ─────────────────────────────────────────────────────────


class TestCancelTask:
    async def test_transitions_to_cancelled(self, manager):
        task = await manager.create_task(TaskType.GOSSIP_SCRAPE, user_id=1)

        result = await manager.cancel_task(task.id)
        assert result is True

        updated = await manager.get_task(task.id)
        assert updated.status == TaskStatus.CANCELLED


# ── subscribe ───────────────────────────────────────────────────────────


class TestSubscribe:
    async def test_subscriber_receives_event_on_update(self, manager):
        task = await manager.create_task(TaskType.GOSSIP_SCRAPE, user_id=1)
        queue = await manager.subscribe(1)

        # Drain the initial seed (active task pushed on subscribe)
        initial = await asyncio.wait_for(queue.get(), timeout=1.0)
        assert initial["id"] == task.id

        # Give the listener a tick to start polling
        await asyncio.sleep(0.05)

        await manager.update_task(task.id, status=TaskStatus.RUNNING, message="Running...")

        # Let the pub/sub message propagate
        await asyncio.sleep(0.1)

        event = await asyncio.wait_for(queue.get(), timeout=2.0)
        assert event["status"] == "running"

        await manager.unsubscribe(1, queue)
