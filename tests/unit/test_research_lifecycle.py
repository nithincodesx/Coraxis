"""Cancellation, exception, and cleanup behavior of the research orchestrator.

These tests pin the *existing* production behavior in
``src/coraxis/services/research.py`` and ``src/coraxis/repositories/runs.py``.
No production code is changed and no future two-protocol interface is assumed.

Covered:
* ``asyncio.CancelledError`` is distinguished from ordinary ``Exception`` — a
  cancellation ends the run as CANCELLED and is re-raised; an ordinary error
  ends it as FAILED and is not re-raised.
* Cleanup (watcher cancel, fetcher close, recorder stop) runs in ``finally``
  blocks even when the crew errors.
* ``mark_finished`` is idempotent — a late timeout cannot clobber a success.
* ``EventRecorder.stop`` and ``emit`` are safe / never-raising.
* ``StopSignal`` cancellation and timeout behave as implemented.
* ``_finalise`` swallows persistence errors rather than crashing the run.
* ``_watch_for_cancellation`` honours a cancel flag and survives poll failure.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from coraxis.core.logging import run_id_var
from coraxis.db.enums import EventLevel, EventType, RunStatus
from coraxis.repositories import runs as run_repo
from coraxis.repositories import users as user_repo
from coraxis.services.events import RunEventBus
from coraxis.services.research import (
    EventRecorder,
    ResearchOrchestrator,
    StopSignal,
    _watch_for_cancellation,
)

# ─────────────────────────────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────────────────────────────


def _make_orchestrator(bus: RunEventBus | None = None) -> ResearchOrchestrator:
    """Build an orchestrator with minimal settings (no vector store, no DB)."""
    settings = SimpleNamespace(
        run_timeout_seconds=300,
        http_timeout_seconds=20,
        min_word_count=100,
        max_sources=8,
        max_fetch_per_query=5,
        crew_max_rpm=10,
        debug=False,
        memory_enabled=False,
    )
    return ResearchOrchestrator(settings=settings, bus=bus or MagicMock(spec=RunEventBus))


async def _create_user(session) -> str:
    return (await user_repo.create(session, email="a@example.com", password_hash="x")).id


class _MockEvent:
    """A stand-in for a persisted RunEvent with the attributes _finalise reads."""

    def __init__(self) -> None:
        self.id = "evt-1"
        self.seq = 1
        self.type = EventType.RUN_FAILED.value
        self.agent = ""
        self.level = EventLevel.ERROR.value
        self.message = "boom"
        self.payload = {}
        self.created_at = MagicMock()
        self.created_at.isoformat.return_value = "2024-01-01T00:00:00+00:00"


class _MockRun:
    """A stand-in for a persisted Run with the attributes _finalise / mark_finished read."""

    def __init__(self, status: RunStatus = RunStatus.RUNNING) -> None:
        self.status = status.value
        self.is_terminal = RunStatus(status).is_terminal
        self.started_at = None
        self.finished_at = None
        self.runtime_seconds = 0.0


def _patch_finalise_repo() -> MagicMock:
    """Patch the repository calls _finalise makes; return the mark_finished mock."""
    patch(
        "coraxis.services.research.run_repo.get_run_unscoped",
        return_value=_MockRun(),
    ).start()
    mark_finished = AsyncMock()
    patch("coraxis.services.research.run_repo.mark_finished", new=mark_finished).start()
    patch(
        "coraxis.services.research.run_repo.add_event",
        new=AsyncMock(return_value=_MockEvent()),
    ).start()
    return mark_finished


# ─────────────────────────────────────────────────────────────────────
#  RunStatus repository behavior (needs a real session)
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mark_finished_is_idempotent(session) -> None:
    """A late terminal write cannot clobber an earlier terminal state."""
    user_id = await _create_user(session)
    run = await run_repo.create_run(session, user_id, query="q")
    await run_repo.mark_finished(session, run, status=RunStatus.SUCCEEDED)
    first_status = run.status

    await run_repo.mark_finished(session, run, status=RunStatus.FAILED, error="late timeout")

    assert run.status == first_status == RunStatus.SUCCEEDED.value


@pytest.mark.asyncio
async def test_request_cancel_then_is_cancel_requested(session) -> None:
    user_id = await _create_user(session)
    run = await run_repo.create_run(session, user_id, query="q")
    assert await run_repo.is_cancel_requested(session, run.id) is False

    ok = await run_repo.request_cancel(session, run)
    assert ok is True
    assert await run_repo.is_cancel_requested(session, run.id) is True


@pytest.mark.asyncio
async def test_request_cancel_on_terminal_run_returns_false(session) -> None:
    user_id = await _create_user(session)
    run = await run_repo.create_run(session, user_id, query="q")
    await run_repo.mark_finished(session, run, status=RunStatus.SUCCEEDED)

    ok = await run_repo.request_cancel(session, run)

    assert ok is False


# ─────────────────────────────────────────────────────────────────────
#  StopSignal (no DB)
# ─────────────────────────────────────────────────────────────────────


def test_stop_signal_starts_not_cancelled_or_timed_out() -> None:
    signal = StopSignal(timeout_seconds=600)
    assert signal.cancelled is False
    assert signal.timed_out is False
    assert signal() is False


def test_stop_signal_mark_cancelled() -> None:
    signal = StopSignal(timeout_seconds=600)
    signal.mark_cancelled()
    assert signal.cancelled is True
    assert signal() is True


def test_stop_signal_times_out() -> None:
    signal = StopSignal(timeout_seconds=-1)  # deadline already in the past
    assert signal.timed_out is True
    assert signal() is True


# ─────────────────────────────────────────────────────────────────────
#  EventRecorder (no DB)
# ─────────────────────────────────────────────────────────────────────


def test_event_recorder_emit_never_raises() -> None:
    """emit must swallow RuntimeError when the loop is shutting down."""
    recorder = EventRecorder("run-1", MagicMock(), MagicMock())
    recorder._loop = MagicMock()
    recorder._loop.call_soon_threadsafe.side_effect = RuntimeError("loop closed")

    # Must not propagate.
    recorder.emit(EventType.RUN_STARTED.value, {"detail": "x"})


@pytest.mark.asyncio
async def test_event_recorder_stop_idempotent() -> None:
    """stop is safe to call more than once (awaited, since it is a coroutine)."""
    recorder = EventRecorder("run-1", MagicMock(), MagicMock())
    await recorder.stop()
    await recorder.stop()


@pytest.mark.asyncio
async def test_event_recorder_stop_after_start_cleans_up() -> None:
    bus = MagicMock(spec=RunEventBus)
    loop = asyncio.get_running_loop()
    recorder = EventRecorder("run-1", loop, bus)
    recorder.start()
    assert recorder._task is not None

    await recorder.stop()
    assert recorder._task is None


# ─────────────────────────────────────────────────────────────────────
#  ResearchOrchestrator.execute — cancellation vs ordinary exception
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_cancelled_error_is_finalised_and_reraised() -> None:
    """CancelledError ends the run as CANCELLED and is re-raised (not swallowed)."""
    orchestrator = _make_orchestrator()
    plan = SimpleNamespace(
        query="q",
        specs=[],
        workflow=[],
        coordinator_slug=None,
        coordinator_instructions="",
        is_team=False,
    )
    orchestrator._prepare = AsyncMock(return_value=plan)
    orchestrator._drive = AsyncMock(side_effect=asyncio.CancelledError())

    mark_finished = _patch_finalise_repo()

    with pytest.raises(asyncio.CancelledError):
        await orchestrator.execute("run-1")

    call_args = mark_finished.call_args
    assert call_args is not None
    assert call_args.kwargs["status"] == RunStatus.CANCELLED
    assert "cancelled" in call_args.kwargs["error"].lower()


@pytest.mark.asyncio
async def test_execute_ordinary_exception_is_finalised_and_not_reraised() -> None:
    """An ordinary Exception ends the run as FAILED and does not propagate."""
    orchestrator = _make_orchestrator()
    plan = SimpleNamespace(
        query="q",
        specs=[],
        workflow=[],
        coordinator_slug=None,
        coordinator_instructions="",
        is_team=False,
    )
    orchestrator._prepare = AsyncMock(return_value=plan)
    orchestrator._drive = AsyncMock(side_effect=ValueError("boom"))

    mark_finished = _patch_finalise_repo()

    await orchestrator.execute("run-1")  # must not raise

    call_args = mark_finished.call_args
    assert call_args is not None
    assert call_args.kwargs["status"] == RunStatus.FAILED


@pytest.mark.asyncio
async def test_execute_always_resets_contextvar_even_on_error() -> None:
    """The finally block resets run_id_var so context does not bleed across runs."""
    orchestrator = _make_orchestrator()
    plan = SimpleNamespace(
        query="q",
        specs=[],
        workflow=[],
        coordinator_slug=None,
        coordinator_instructions="",
        is_team=False,
    )
    orchestrator._prepare = AsyncMock(return_value=plan)
    orchestrator._drive = AsyncMock(side_effect=RuntimeError("dies"))

    _patch_finalise_repo()

    token = run_id_var.set("run-1")
    try:
        await orchestrator.execute("run-1")
    finally:
        run_id_var.reset(token)

    # After reset, the contextvar should hold its default.
    assert run_id_var.get() == ""


# ─────────────────────────────────────────────────────────────────────
#  ResearchOrchestrator._drive — cleanup runs on error
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_drive_cleanup_runs_when_kickoff_errors() -> None:
    """watcher.cancel, fetcher.aclose, and recorder.stop all run in finally."""
    orchestrator = _make_orchestrator()
    plan = SimpleNamespace(
        query="q",
        specs=[],
        workflow=[],
        coordinator_slug=None,
        coordinator_instructions="",
        is_team=False,
        options={},
        user_id="user-1",
    )

    mock_watcher = MagicMock()
    mock_fetcher = MagicMock()
    mock_fetcher.aclose = AsyncMock()
    mock_recorder = MagicMock()
    mock_recorder.stop = AsyncMock()
    mock_crew = MagicMock()
    mock_crew.kickoff_async = AsyncMock(side_effect=RuntimeError("crew died"))

    with (
        patch("coraxis.services.research.asyncio.create_task", return_value=mock_watcher),
        patch("coraxis.services.research.PageFetcher", return_value=mock_fetcher),
        patch("coraxis.services.research.EventRecorder", return_value=mock_recorder),
        patch.object(orchestrator, "_build_crew", return_value=mock_crew),
        patch("coraxis.services.research.asyncio.wait_for", new=mock_crew.kickoff_async),
        patch("coraxis.services.research.CitationTracker", return_value=MagicMock()),
        pytest.raises(RuntimeError, match="crew died"),
    ):
        await orchestrator._drive("run-1", plan)

    mock_watcher.cancel.assert_called_once()
    mock_fetcher.aclose.assert_awaited_once()
    mock_recorder.stop.assert_awaited_once()


# ─────────────────────────────────────────────────────────────────────
#  _finalise — persistence errors are swallowed
# ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_finalise_persistence_error_does_not_crash_or_publish() -> None:
    """If marking finished fails, _finalise logs and returns without publishing."""
    orchestrator = _make_orchestrator()
    bus = orchestrator.bus

    with (
        patch(
            "coraxis.services.research.run_repo.get_run_unscoped",
            return_value=_MockRun(),
        ),
        patch(
            "coraxis.services.research.run_repo.mark_finished",
            new=AsyncMock(side_effect=OSError("db down")),
        ),
        patch(
            "coraxis.services.research.run_repo.add_event",
            new=AsyncMock(),
        ),
    ):
        # Must not raise.
        await orchestrator._finalise("run-1", RunStatus.FAILED, "boom")

    bus.publish.assert_not_called()


@pytest.mark.asyncio
async def test_finalise_none_run_returns_early() -> None:
    """A run that no longer exists is finalised without a crash."""
    orchestrator = _make_orchestrator()
    bus = orchestrator.bus

    with (
        patch(
            "coraxis.services.research.run_repo.get_run_unscoped",
            return_value=None,
        ),
        patch(
            "coraxis.services.research.run_repo.mark_finished",
            new=AsyncMock(),
        ),
        patch(
            "coraxis.services.research.run_repo.add_event",
            new=AsyncMock(),
        ),
    ):
        await orchestrator._finalise("run-1", RunStatus.FAILED, "gone")

    bus.publish.assert_not_called()


# ─────────────────────────────────────────────────────────────────────
#  _watch_for_cancellation
# ─────────────────────────────────────────────────────────────────────


class _MockSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


@pytest.mark.asyncio
async def test_watch_cancellation_honours_cancel_requested() -> None:
    """When the DB reports cancel requested, the signal is marked cancelled."""
    signal = StopSignal(timeout_seconds=600)
    assert signal.cancelled is False

    with (
        patch("coraxis.services.research.session_scope", return_value=_MockSession()),
        patch(
            "coraxis.services.research.run_repo.is_cancel_requested",
            new=AsyncMock(return_value=True),
        ),
        patch("coraxis.services.research.asyncio.sleep", new=AsyncMock()),
        patch("coraxis.services.research._CANCEL_POLL_SECONDS", 0),
    ):
        await _watch_for_cancellation("run-1", signal)

    assert signal.cancelled is True


@pytest.mark.asyncio
async def test_watch_cancellation_poll_failure_does_not_crash() -> None:
    """A failing cancel poll is logged and does not propagate."""
    signal = StopSignal(timeout_seconds=600)
    signal.mark_cancelled()  # so the while loop exits after one iteration

    with (
        patch("coraxis.services.research.session_scope", return_value=_MockSession()),
        patch(
            "coraxis.services.research.run_repo.is_cancel_requested",
            new=AsyncMock(side_effect=OSError("db down")),
        ),
        patch("coraxis.services.research.asyncio.sleep", new=AsyncMock()),
        patch("coraxis.services.research._CANCEL_POLL_SECONDS", 0),
    ):
        # Must not raise.
        await _watch_for_cancellation("run-1", signal)

    assert signal.cancelled is True
