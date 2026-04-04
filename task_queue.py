"""
Async task queue with concurrency, rate limiting, priority scheduling,
and dependency-aware execution.
"""

from __future__ import annotations

import asyncio
import heapq
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

import interro_claw.config as config

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    PENDING = "pending"
    WAITING = "waiting"   # blocked on dependencies
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    id: str
    description: str
    agent_name: str
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    error: str | None = None
    depends_on: list[str] = field(default_factory=list)
    priority: int = 5  # 0=lowest, 10=highest — higher runs first
    elapsed_ms: int = 0

    def __lt__(self, other: Task) -> bool:
        # Higher priority = smaller sort key (runs first in min-heap)
        return self.priority > other.priority


class TaskQueue:
    """
    Async task queue with:
    - Priority-based scheduling (higher priority runs first)
    - Bounded concurrency (semaphore)
    - Token-bucket rate limiter (requests per minute)
    - Dependency graph: tasks wait until their prerequisites complete
    """

    def __init__(
        self,
        max_concurrent: int | None = None,
        rate_limit_rpm: int | None = None,
    ) -> None:
        self._max_concurrent = max_concurrent or config.MAX_CONCURRENT_AGENTS
        self._rpm = rate_limit_rpm or config.RATE_LIMIT_RPM
        self._semaphore = asyncio.Semaphore(self._max_concurrent)
        self._tasks: dict[str, Task] = {}
        self._heap: list[Task] = []  # priority heap
        self._events: dict[str, asyncio.Event] = {}
        # Rate-limiter state
        self._token_bucket = float(self._rpm)
        self._bucket_max = float(self._rpm)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    # -- public API ---------------------------------------------------------

    def add(self, task: Task) -> None:
        self._tasks[task.id] = task
        self._events[task.id] = asyncio.Event()
        heapq.heappush(self._heap, task)

    def get(self, task_id: str) -> Task | None:
        return self._tasks.get(task_id)

    @property
    def all_tasks(self) -> list[Task]:
        return list(self._tasks.values())

    async def execute(
        self,
        task: Task,
        run_fn: Callable[[Task], Coroutine[Any, Any, str]],
    ) -> Task:
        """Wait for dependencies, then run via semaphore + rate limiter."""
        if task.depends_on:
            task.status = TaskStatus.WAITING
            logger.info("Task %s (pri=%d) waiting on: %s", task.id, task.priority, task.depends_on)
            for dep_id in task.depends_on:
                event = self._events.get(dep_id)
                if event:
                    await event.wait()
                    dep = self._tasks.get(dep_id)
                    if dep and dep.status == TaskStatus.FAILED:
                        task.status = TaskStatus.FAILED
                        task.error = f"Dependency {dep_id} failed"
                        logger.error("Task %s SKIPPED — dependency %s failed", task.id, dep_id)
                        self._events[task.id].set()
                        return task

        await self._acquire_rate_token()
        async with self._semaphore:
            task.status = TaskStatus.RUNNING
            logger.info("Task %s [%s] pri=%d -> RUNNING", task.id, task.agent_name, task.priority)
            start = time.monotonic()
            try:
                task.result = await run_fn(task)
                task.status = TaskStatus.COMPLETED
                task.elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.info(
                    "Task %s [%s] -> COMPLETED (%dms)",
                    task.id, task.agent_name, task.elapsed_ms,
                )
            except Exception as exc:
                task.status = TaskStatus.FAILED
                task.error = str(exc)
                task.elapsed_ms = int((time.monotonic() - start) * 1000)
                logger.error("Task %s [%s] -> FAILED: %s", task.id, task.agent_name, exc)

        self._events[task.id].set()
        return task

    async def execute_all(
        self,
        run_fn: Callable[[Task], Coroutine[Any, Any, str]],
    ) -> list[Task]:
        """Execute every pending task concurrently, respecting dependencies and priority."""
        # Pop from heap in priority order
        ordered: list[Task] = []
        while self._heap:
            ordered.append(heapq.heappop(self._heap))
        pending = [
            t for t in ordered
            if t.status in (TaskStatus.PENDING, TaskStatus.WAITING)
        ]
        results = await asyncio.gather(
            *(self.execute(t, run_fn) for t in pending),
            return_exceptions=False,
        )
        return list(results)

    # -- rate limiter -------------------------------------------------------

    async def _acquire_rate_token(self) -> None:
        """Block until a rate-limit token is available (token-bucket algorithm)."""
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._token_bucket = min(
                    self._bucket_max,
                    self._token_bucket + elapsed * (self._rpm / 60.0),
                )
                self._last_refill = now
                if self._token_bucket >= 1.0:
                    self._token_bucket -= 1.0
                    return
            await asyncio.sleep(0.1)
