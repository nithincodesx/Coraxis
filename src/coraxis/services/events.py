"""In-process event bus for live run progress.

The previous implementation registered a plain ``asyncio.Queue`` subscriber
that was fed by calling ``put_nowait`` from a CrewAI worker thread. ``asyncio``
queues are not thread-safe, so events could be lost, reordered, or raise.

Here, :meth:`RunEventBus.publish` is safe to call from any thread: it hops onto
the event loop with ``call_soon_threadsafe`` before touching a queue. A slow or
disconnected subscriber loses its own events (bounded queue, drop-oldest) but
can never stall the producer.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from coraxis.core.logging import get_logger

logger = get_logger("events")

#: Per-subscriber buffer. Deep enough to absorb a burst, shallow enough that a
#: dead client cannot pin memory.
_QUEUE_SIZE = 512


class RunEventBus:
    """Fan-out of run events to interested SSE subscribers."""

    def __init__(self) -> None:
        self._subscribers: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Record the serving event loop. Called once during app startup."""
        self._loop = loop

    # ── Subscription ─────────────────────────────────────────────────

    def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=_QUEUE_SIZE)
        self._subscribers.setdefault(run_id, set()).add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        bucket = self._subscribers.get(run_id)
        if not bucket:
            return
        bucket.discard(queue)
        if not bucket:
            self._subscribers.pop(run_id, None)

    def subscriber_count(self, run_id: str) -> int:
        return len(self._subscribers.get(run_id, ()))

    # ── Publishing ───────────────────────────────────────────────────

    def publish(self, run_id: str, event: dict[str, Any]) -> None:
        """Deliver an event. Safe from any thread; never blocks."""
        queues = list(self._subscribers.get(run_id, ()))
        if not queues:
            return

        loop = self._loop
        for queue in queues:
            if loop is not None and loop.is_running():
                try:
                    loop.call_soon_threadsafe(self._offer, queue, event)
                    continue
                except RuntimeError:
                    # Loop closed between the check and the call; fall through.
                    pass
            self._offer(queue, event)

    @staticmethod
    def _offer(queue: asyncio.Queue[dict[str, Any]], event: dict[str, Any]) -> None:
        """Enqueue without blocking, dropping the oldest entry when full."""
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()  # discard the oldest
                queue.put_nowait(event)
            except (asyncio.QueueEmpty, asyncio.QueueFull):  # pragma: no cover
                logger.warning("dropped an event for a saturated subscriber")

    @asynccontextmanager
    async def subscription(self, run_id: str) -> AsyncIterator[asyncio.Queue[dict[str, Any]]]:
        """Context-managed subscription that always cleans up."""
        queue = self.subscribe(run_id)
        try:
            yield queue
        finally:
            self.unsubscribe(run_id, queue)

    def clear(self) -> None:
        """Drop every subscriber. Shutdown and tests only."""
        self._subscribers.clear()


#: Process-wide bus. One per worker process.
event_bus = RunEventBus()
