"""
Background Task Manager Service

Manages background tasks with status tracking and SSE (Server-Sent Events) for real-time updates.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Callable, Awaitable
from enum import Enum
from dataclasses import dataclass, field, asdict
import json

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """Task status enum"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskType(str, Enum):
    """Types of background tasks"""
    MOVIE_DISCOVERY = "movie_discovery"
    TV_DISCOVERY = "tv_discovery"
    GOSSIP_SCRAPE = "gossip_scrape"
    CONTENT_RERANKING = "content_reranking"


def _utc_now():
    """Get current UTC time (timezone-aware)"""
    return datetime.now(timezone.utc)


@dataclass
class Task:
    """Represents a background task"""
    id: str
    type: TaskType
    name: str
    user_id: int
    status: TaskStatus = TaskStatus.PENDING
    progress: int = 0
    message: str = "Waiting to start..."
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = field(default_factory=_utc_now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert task to dictionary for JSON serialization"""
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


class TaskManager:
    """
    Manages background tasks with real-time status updates via SSE.
    
    This is a singleton that stores task state in-memory. In a production
    environment, you might want to use Redis or a database for persistence.
    """
    
    _instance: Optional["TaskManager"] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._tasks: Dict[str, Task] = {}
        self._subscribers: Dict[int, List[asyncio.Queue]] = {}  # user_id -> list of queues
        self._global_subscribers: List[asyncio.Queue] = []
        self._lock = asyncio.Lock()
        self._initialized = True
        
        logger.info("TaskManager initialized")
    
    async def create_task(
        self,
        task_type: TaskType,
        user_id: int,
        name: Optional[str] = None
    ) -> Task:
        """Create a new task"""
        task_id = str(uuid.uuid4())[:8]
        
        # Default names for task types
        default_names = {
            TaskType.MOVIE_DISCOVERY: "Discovering Movies",
            TaskType.TV_DISCOVERY: "Discovering TV Shows",
            TaskType.GOSSIP_SCRAPE: "Scanning for Gossip",
            TaskType.CONTENT_RERANKING: "Re-ranking Content",
        }
        
        task = Task(
            id=task_id,
            type=task_type,
            name=name or default_names.get(task_type, "Background Task"),
            user_id=user_id,
        )
        
        async with self._lock:
            self._tasks[task_id] = task
        
        # Notify subscribers
        await self._notify_subscribers(user_id, task)
        
        logger.info(f"Created task {task_id}: {task.name} for user {user_id}")
        return task
    
    async def update_task(
        self,
        task_id: str,
        status: Optional[TaskStatus] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None
    ) -> Optional[Task]:
        """Update task status and notify subscribers"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            
            if status:
                task.status = status
                if status == TaskStatus.RUNNING and not task.started_at:
                    task.started_at = datetime.now(timezone.utc)
                elif status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
                    task.completed_at = datetime.now(timezone.utc)
            
            if progress is not None:
                task.progress = min(100, max(0, progress))
            
            if message:
                task.message = message
            
            if result:
                task.result = result
            
            if error:
                task.error = error
        
        # Notify subscribers
        await self._notify_subscribers(task.user_id, task)
        
        logger.debug(f"Updated task {task_id}: status={task.status}, progress={task.progress}%")
        return task
    
    async def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID"""
        return self._tasks.get(task_id)
    
    async def get_user_tasks(
        self, 
        user_id: int, 
        active_only: bool = True,
        include_recent_completed: bool = True,
        recent_seconds: int = 30
    ) -> List[Task]:
        """
        Get all tasks for a user.
        
        Args:
            user_id: The user's ID
            active_only: If True, only return active (pending/running) tasks
            include_recent_completed: If True, also include tasks completed within recent_seconds
            recent_seconds: How many seconds to consider "recent" for completed tasks
        """
        tasks = [t for t in self._tasks.values() if t.user_id == user_id]
        
        if active_only:
            active_tasks = [t for t in tasks if t.status in (TaskStatus.PENDING, TaskStatus.RUNNING)]
            
            # Also include recently completed tasks so frontend can see them
            if include_recent_completed:
                now = datetime.now(timezone.utc)
                recent_completed = []
                for t in tasks:
                    if t.status in (TaskStatus.COMPLETED, TaskStatus.FAILED) and t.completed_at:
                        completed = t.completed_at
                        # Handle offset-naive datetimes
                        if completed.tzinfo is None:
                            completed = completed.replace(tzinfo=timezone.utc)
                        if (now - completed).total_seconds() < recent_seconds:
                            recent_completed.append(t)
                tasks = active_tasks + recent_completed
            else:
                tasks = active_tasks
        
        return sorted(tasks, key=lambda t: t.created_at, reverse=True)
    
    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task"""
        task = await self.update_task(
            task_id,
            status=TaskStatus.CANCELLED,
            message="Task cancelled"
        )
        return task is not None
    
    async def subscribe(self, user_id: int) -> asyncio.Queue:
        """Subscribe to task updates for a user"""
        queue: asyncio.Queue = asyncio.Queue()
        
        async with self._lock:
            if user_id not in self._subscribers:
                self._subscribers[user_id] = []
            self._subscribers[user_id].append(queue)
        
        # Send current active tasks
        tasks = await self.get_user_tasks(user_id, active_only=True)
        for task in tasks:
            await queue.put(task.to_dict())
        
        logger.debug(f"User {user_id} subscribed to task updates")
        return queue
    
    async def unsubscribe(self, user_id: int, queue: asyncio.Queue):
        """Unsubscribe from task updates"""
        async with self._lock:
            if user_id in self._subscribers:
                try:
                    self._subscribers[user_id].remove(queue)
                except ValueError:
                    pass
        
        logger.debug(f"User {user_id} unsubscribed from task updates")
    
    async def _notify_subscribers(self, user_id: int, task: Task):
        """Notify all subscribers of a task update"""
        task_data = task.to_dict()
        
        # Notify user-specific subscribers
        if user_id in self._subscribers:
            for queue in self._subscribers[user_id]:
                try:
                    await queue.put(task_data)
                except Exception as e:
                    logger.error(f"Error notifying subscriber: {e}")
        
        # Notify global subscribers
        for queue in self._global_subscribers:
            try:
                await queue.put(task_data)
            except Exception as e:
                logger.error(f"Error notifying global subscriber: {e}")
    
    async def run_task(
        self,
        task_id: str,
        task_func: Callable[["Task", "TaskManager"], Awaitable[Dict[str, Any]]]
    ):
        """
        Run a task function and handle status updates.
        
        The task_func should accept (task, task_manager) and can call
        task_manager.update_task() to report progress.
        """
        task = await self.get_task(task_id)
        if not task:
            logger.error(f"Task {task_id} not found")
            return
        
        try:
            # Mark as running
            await self.update_task(
                task_id,
                status=TaskStatus.RUNNING,
                message="Starting..."
            )
            
            # Run the task function
            result = await task_func(task, self)
            
            # Mark as completed
            await self.update_task(
                task_id,
                status=TaskStatus.COMPLETED,
                progress=100,
                message="Completed successfully",
                result=result
            )
            
        except asyncio.CancelledError:
            await self.update_task(
                task_id,
                status=TaskStatus.CANCELLED,
                message="Task cancelled"
            )
            raise
            
        except Exception as e:
            logger.error(f"Task {task_id} failed: {e}")
            await self.update_task(
                task_id,
                status=TaskStatus.FAILED,
                message=f"Failed: {str(e)}",
                error=str(e)
            )
    
    def cleanup_old_tasks(self, max_age_hours: int = 24):
        """Remove tasks older than max_age_hours"""
        cutoff = datetime.now(timezone.utc)
        to_remove = []
        
        for task_id, task in self._tasks.items():
            if task.completed_at:
                age = (cutoff - task.completed_at).total_seconds() / 3600
                if age > max_age_hours:
                    to_remove.append(task_id)
        
        for task_id in to_remove:
            del self._tasks[task_id]
        
        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old tasks")


# Global singleton instance
_task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """Get the global TaskManager instance"""
    global _task_manager
    if _task_manager is None:
        _task_manager = TaskManager()
    return _task_manager
