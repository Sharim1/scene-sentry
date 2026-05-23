"""
Background Task Manager Service

Redis-backed task state with Pub/Sub for real-time SSE updates.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

_TASK_TTL = 86400


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    GOSSIP_SCRAPE = "gossip_scrape"
    CONTENT_RERANKING = "content_reranking"


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Task:
    id: str
    type: TaskType
    name: str
    user_id: int
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    message: str = "Waiting to start..."
    result: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "user_id": self.user_id,
            "status": self.status.value,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        def _dt(v: str | None) -> datetime | None:
            return datetime.fromisoformat(v) if v else None

        return cls(
            id=d["id"],
            type=TaskType(d["type"]),
            name=d["name"],
            user_id=d["user_id"],
            status=TaskStatus(d["status"]),
            progress=d.get("progress", 0),
            message=d.get("message", ""),
            result=d.get("result"),
            error=d.get("error"),
            created_at=_dt(d.get("created_at")),
            started_at=_dt(d.get("started_at")),
            completed_at=_dt(d.get("completed_at")),
        )


_DEFAULT_NAMES = {
    TaskType.GOSSIP_SCRAPE: "Scanning for Gossip",
    TaskType.CONTENT_RERANKING: "Re-ranking Content",
}


class TaskManager:
    def __init__(self, redis_client):
        self._redis = redis_client
        self._listeners: dict[int, list[tuple[asyncio.Queue, asyncio.Task]]] = {}
        self._lock = asyncio.Lock()

    async def create_task(self, task_type: TaskType, user_id: int, name: str | None = None) -> Task:
        task_id = str(uuid.uuid4())[:8]
        task = Task(
            id=task_id,
            type=task_type,
            name=name or _DEFAULT_NAMES.get(task_type, "Background Task"),
            user_id=user_id,
        )
        await self._store(task)
        await self._publish(user_id, task.to_dict())
        logger.info("Created task %s for user %s", task_id, user_id)
        return task

    async def update_task(
        self,
        task_id: str,
        status: TaskStatus | None = None,
        progress: int | None = None,
        message: str | None = None,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> Task | None:
        task = await self.get_task(task_id)
        if not task:
            return None

        if status:
            task.status = status
            if status == TaskStatus.RUNNING and not task.started_at:
                task.started_at = _utc_now()
            elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                task.completed_at = _utc_now()
        if progress is not None:
            task.progress = min(100, max(0, progress))
        if message:
            task.message = message
        if result:
            task.result = result
        if error:
            task.error = error

        await self._store(task)
        await self._publish(task.user_id, task.to_dict())
        return task

    async def get_task(self, task_id: str) -> Task | None:
        data = await self._redis.get(f"task:{task_id}")
        if not data:
            return None
        return Task.from_dict(json.loads(data))

    async def get_user_tasks(
        self,
        user_id: int,
        active_only: bool = True,
        include_recent_completed: bool = True,
        recent_seconds: int = 30,
    ) -> list[Task]:
        task_ids = await self._redis.smembers(f"user-tasks:{user_id}")
        tasks = []
        for raw_id in task_ids:
            tid = raw_id.decode() if isinstance(raw_id, bytes) else raw_id
            task = await self.get_task(tid)
            if task:
                tasks.append(task)

        if active_only:
            active = [t for t in tasks if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]
            if include_recent_completed:
                now = _utc_now()
                for t in tasks:
                    if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED) and t.completed_at:
                        age = (
                            now - t.completed_at.replace(tzinfo=UTC)
                            if t.completed_at.tzinfo is None
                            else now - t.completed_at
                        )
                        if age.total_seconds() < recent_seconds:
                            active.append(t)
            tasks = active

        return sorted(tasks, key=lambda t: t.created_at, reverse=True)

    async def cancel_task(self, task_id: str) -> bool:
        task = await self.update_task(task_id, status=TaskStatus.CANCELLED, message="Task cancelled")
        return task is not None

    async def subscribe(self, user_id: int) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(f"task-updates:{user_id}")
        listener = asyncio.create_task(self._pubsub_listener(pubsub, queue))

        async with self._lock:
            if user_id not in self._listeners:
                self._listeners[user_id] = []
            self._listeners[user_id].append((queue, listener))

        active = await self.get_user_tasks(user_id, active_only=True)
        for task in active:
            await queue.put(task.to_dict())

        return queue

    async def unsubscribe(self, user_id: int, queue: asyncio.Queue) -> None:
        async with self._lock:
            pairs = self._listeners.get(user_id, [])
            for i, (q, listener) in enumerate(pairs):
                if q is queue:
                    listener.cancel()
                    pairs.pop(i)
                    break

    async def run_task(
        self,
        task_id: str,
        task_func: Callable[["Task", "TaskManager"], Awaitable[dict[str, Any]]],
    ) -> None:
        task = await self.get_task(task_id)
        if not task:
            logger.error("Task %s not found", task_id)
            return
        try:
            await self.update_task(task_id, status=TaskStatus.RUNNING, message="Starting...")
            result = await task_func(task, self)
            await self.update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                progress=100,
                message="Completed successfully",
                result=result,
            )
        except asyncio.CancelledError:
            await self.update_task(task_id, status=TaskStatus.CANCELLED, message="Task cancelled")
            raise
        except Exception as e:
            logger.error("Task %s failed: %s", task_id, e)
            await self.update_task(
                task_id,
                status=TaskStatus.FAILED,
                message="Task failed. Check server logs for details.",
                error="Internal error",
            )

    # ── internals ───────────────────────────────────────────────────────

    async def _store(self, task: Task) -> None:
        pipe = self._redis.pipeline()
        pipe.setex(f"task:{task.id}", _TASK_TTL, json.dumps(task.to_dict()))
        pipe.sadd(f"user-tasks:{task.user_id}", task.id)
        pipe.expire(f"user-tasks:{task.user_id}", _TASK_TTL)
        await pipe.execute()

    async def _publish(self, user_id: int, data: dict) -> None:
        await self._redis.publish(f"task-updates:{user_id}", json.dumps(data))

    async def _pubsub_listener(self, pubsub, queue: asyncio.Queue) -> None:
        try:
            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message["type"] == "message":
                    raw = message["data"]
                    payload = raw.decode() if isinstance(raw, bytes) else raw
                    await queue.put(json.loads(payload))
                else:
                    await asyncio.sleep(0.01)
        except asyncio.CancelledError:
            pass
        finally:
            try:
                await pubsub.aclose()
            except Exception:
                pass


_task_manager: TaskManager | None = None


def get_task_manager() -> TaskManager:
    global _task_manager
    if _task_manager is None:
        import redis.asyncio as aioredis

        from app.config import settings

        _task_manager = TaskManager(aioredis.from_url(settings.redis_url))
    return _task_manager
