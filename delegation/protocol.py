"""
Agent Delegation Protocol

Allows agents to request help from other agents during execution:
1. Agent A creates a DelegationRequest specifying what it needs + which agent
2. Protocol queues the request with the orchestrator
3. Delegate agent runs the sub-task
4. Result is returned to the requesting agent

The delegator can optionally wait (blocking) or continue and merge later.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)


class DelegationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DelegationRequest:
    """A request from one agent to another."""
    id: str = ""
    requester_agent: str = ""
    delegate_agent: str = ""
    task: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    priority: int = 5
    status: DelegationStatus = DelegationStatus.PENDING
    result: str = ""
    error: str = ""
    created_at: float = 0.0
    completed_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = f"deleg-{uuid.uuid4().hex[:8]}"
        if not self.created_at:
            self.created_at = time.time()


class DelegationProtocol:
    """
    Manages agent-to-agent delegation.

    The orchestrator registers a dispatch_fn that actually runs agent tasks.
    Agents call `delegate()` to request help, and await the result.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[DelegationRequest] = asyncio.Queue()
        self._results: dict[str, asyncio.Event] = {}
        self._requests: dict[str, DelegationRequest] = {}
        self._dispatch_fn: Callable[..., Coroutine[Any, Any, str]] | None = None
        self._processing = False

    def set_dispatch_fn(
        self,
        fn: Callable[[str, str, dict[str, Any]], Coroutine[Any, Any, str]],
    ) -> None:
        """Register the function that runs delegated tasks.
        Signature: fn(agent_name, task_description, context) -> result_str
        """
        self._dispatch_fn = fn

    async def delegate(
        self,
        requester: str,
        delegate_agent: str,
        task: str,
        context: dict[str, Any] | None = None,
        priority: int = 5,
    ) -> DelegationRequest:
        """Submit a delegation request and wait for the result."""
        req = DelegationRequest(
            requester_agent=requester,
            delegate_agent=delegate_agent,
            task=task,
            context=context or {},
            priority=priority,
        )
        self._requests[req.id] = req
        self._results[req.id] = asyncio.Event()

        logger.info(
            "Delegation: %s -> %s: %s (id=%s)",
            requester, delegate_agent, task[:80], req.id,
        )

        # If we have a dispatch fn, run immediately
        if self._dispatch_fn:
            await self._execute(req)
        else:
            await self._queue.put(req)

        # Wait for completion
        await self._results[req.id].wait()
        return self._requests[req.id]

    async def delegate_async(
        self,
        requester: str,
        delegate_agent: str,
        task: str,
        context: dict[str, Any] | None = None,
        priority: int = 5,
    ) -> str:
        """Submit delegation without waiting — returns request ID."""
        req = DelegationRequest(
            requester_agent=requester,
            delegate_agent=delegate_agent,
            task=task,
            context=context or {},
            priority=priority,
        )
        self._requests[req.id] = req
        self._results[req.id] = asyncio.Event()

        if self._dispatch_fn:
            asyncio.create_task(self._execute(req))
        else:
            await self._queue.put(req)

        return req.id

    async def wait_for(self, request_id: str) -> DelegationRequest:
        """Wait for a previously submitted async delegation."""
        event = self._results.get(request_id)
        if event:
            await event.wait()
        return self._requests.get(request_id, DelegationRequest())

    async def _execute(self, req: DelegationRequest) -> None:
        """Execute a delegation request."""
        req.status = DelegationStatus.RUNNING
        try:
            result = await self._dispatch_fn(
                req.delegate_agent, req.task, req.context,
            )
            req.result = result
            req.status = DelegationStatus.COMPLETED
        except Exception as e:
            req.error = str(e)
            req.status = DelegationStatus.FAILED
            logger.error("Delegation %s failed: %s", req.id, e)
        finally:
            req.completed_at = time.time()
            event = self._results.get(req.id)
            if event:
                event.set()

    async def process_queue(self) -> None:
        """Process queued delegation requests (for use without dispatch_fn)."""
        self._processing = True
        while self._processing:
            try:
                req = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._execute(req)
            except asyncio.TimeoutError:
                continue

    def stop(self) -> None:
        self._processing = False

    def get_pending(self) -> list[DelegationRequest]:
        return [r for r in self._requests.values() if r.status == DelegationStatus.PENDING]

    def get_all(self) -> list[DelegationRequest]:
        return list(self._requests.values())


# -- Singleton ---------------------------------------------------------------

_instance: DelegationProtocol | None = None


def get_delegation_protocol() -> DelegationProtocol:
    global _instance
    if _instance is None:
        _instance = DelegationProtocol()
    return _instance
