"""In-process run runner.

Runs execute as asyncio tasks, not daemon threads. That buys three things the
previous implementation could not offer:

* **cancellation** — a task can be cancelled and will actually stop;
* **bounded concurrency** — a semaphore caps total simultaneous runs, so a
  burst of submissions cannot exhaust memory or a provider quota;
* **observability** — the runner knows exactly which runs are live.

The trade-off is that tasks live in one process. Scaling out means replacing
this class with a queue-backed implementation; because the run record already
lives in the database with a status column, that swap does not touch the API or
the orchestrator.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from coraxis.core.logging import get_logger
from coraxis.services.research import ResearchOrchestrator

logger = get_logger("runner")

#: Total simultaneous runs per process. Research is provider-bound, not
#: CPU-bound, so a small number is enough to keep throughput high without
#: tripping per-key rate limits.
DEFAULT_MAX_CONCURRENT = 4


class RunRunner:
    """Schedules and tracks run execution."""

    def __init__(
        self,
        *,
        orchestrator_factory: Callable[[], ResearchOrchestrator] | None = None,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
    ) -> None:
        self._orchestrator_factory = orchestrator_factory or ResearchOrchestrator
        self._semaphore = asyncio.Semaphore(max(1, max_concurrent))
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._accepting = True

    # ── Introspection ────────────────────────────────────────────────

    @property
    def active_run_ids(self) -> list[str]:
        return list(self._tasks)

    @property
    def active_count(self) -> int:
        return len(self._tasks)

    def is_active(self, run_id: str) -> bool:
        return run_id in self._tasks

    # ── Submission ───────────────────────────────────────────────────

    def submit(self, run_id: str) -> bool:
        """Schedule a run. Returns ``False`` if it is already scheduled."""
        if not self._accepting:
            logger.warning("runner is shutting down; refusing run %s", run_id)
            return False

        if run_id in self._tasks:
            logger.debug("run %s is already scheduled", run_id)
            return False

        task = asyncio.create_task(self._execute(run_id), name=f"run:{run_id}")
        self._tasks[run_id] = task

        # A named closure rather than a default-argument lambda: the default
        # argument defeats type inference on `add_done_callback`.
        def forget(_finished: asyncio.Task[None], *, rid: str = run_id) -> None:
            self._tasks.pop(rid, None)

        task.add_done_callback(forget)
        logger.info("run %s scheduled (%d active)", run_id, self.active_count)
        return True

    async def _execute(self, run_id: str) -> None:
        """Wait for a slot, then run to completion."""
        async with self._semaphore:
            orchestrator = self._orchestrator_factory()
            try:
                await orchestrator.execute(run_id)
            except asyncio.CancelledError:
                logger.info("run %s cancelled at the task level", run_id)
                raise
            except Exception:
                # The orchestrator is responsible for writing a terminal status.
                # If it could not, log loudly — the run will be reaped on restart.
                logger.exception("run %s crashed outside the orchestrator", run_id)

    # ── Lifecycle ────────────────────────────────────────────────────

    async def shutdown(self, *, grace_seconds: float = 10.0) -> None:
        """Stop accepting work and give in-flight runs a chance to finish.

        Runs that outlive the grace period are cancelled; their orchestrator
        writes a terminal status on the way out.
        """
        self._accepting = False

        if not self._tasks:
            return

        logger.info("waiting up to %.0fs for %d run(s)", grace_seconds, len(self._tasks))
        _done, pending = await asyncio.wait(list(self._tasks.values()), timeout=grace_seconds)

        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
            logger.warning(
                "cancelled %d run(s) that outlived the shutdown grace period", len(pending)
            )

        self._tasks.clear()


#: Process-wide runner, created on first use so it binds to the running loop.
run_runner = RunRunner()
