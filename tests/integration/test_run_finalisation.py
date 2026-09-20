"""Terminal-state writing.

Regression guard for a bug that only an end-to-end run exposed: `_finalise`
passed `EventLevel.ERROR.value` — a plain string — where the repository expects
the enum member and calls `.value` on it. That raised `AttributeError` inside the
last write of a failed run, so the run never reached a terminal state and sat in
`running` forever. Nothing unit-tested it, because the failure only happens on a
path that requires a real run to fail.
"""

from __future__ import annotations

import pytest

from coraxis.db.enums import EventLevel, EventType, RunStatus

pytestmark = pytest.mark.integration


async def _queue_run(query: str = "why do failed runs need a terminal state") -> str:
    """Create a run row directly, without going through the API."""
    from coraxis.db.session import session_scope
    from coraxis.repositories import runs as run_repo
    from coraxis.repositories import users as user_repo

    async with session_scope() as session:
        user = await user_repo.get_by_email(session, "fixture@example.com")
        if user is None:
            user = await user_repo.create(
                session,
                email="fixture@example.com",
                password_hash="not-a-real-hash",
                display_name="Fixture",
            )
        run = await run_repo.create_run(session, user.id, query=query)
        return run.id


@pytest.mark.parametrize(
    ("status", "expected_event"),
    [
        (RunStatus.FAILED, EventType.RUN_FAILED),
        (RunStatus.CANCELLED, EventType.RUN_CANCELLED),
        (RunStatus.TIMED_OUT, EventType.RUN_TIMED_OUT),
    ],
)
async def test_finalise_writes_a_terminal_status_and_event(
    app: object, status: RunStatus, expected_event: EventType
) -> None:
    """Every terminal outcome must persist, with the matching event type."""
    from coraxis.db.session import session_scope
    from coraxis.repositories import runs as run_repo
    from coraxis.services.research import ResearchOrchestrator

    run_id = await _queue_run()
    orchestrator = ResearchOrchestrator()

    await orchestrator._finalise(run_id, status, "something went wrong")

    async with session_scope() as session:
        run = await run_repo.get_run_unscoped(session, run_id)
        assert run is not None
        assert run.status == status.value
        assert run.finished_at is not None
        assert run.error == "something went wrong"

        events = await run_repo.list_events(session, run_id)
        terminal = [event for event in events if event.type == expected_event.value]
        assert len(terminal) == 1, f"expected one {expected_event.value} event, got {len(terminal)}"

        event = terminal[0]
        assert event.seq >= 1
        # The level is written as the enum's value, not the enum itself.
        assert event.level == (
            EventLevel.ERROR.value if status is RunStatus.FAILED else EventLevel.WARNING.value
        )


async def test_finalise_does_not_clobber_an_already_terminal_run(app: object) -> None:
    """A late timeout must not overwrite a run that already succeeded."""
    from coraxis.db.session import session_scope
    from coraxis.repositories import runs as run_repo
    from coraxis.services.research import ResearchOrchestrator

    run_id = await _queue_run("does a late timeout overwrite success")
    orchestrator = ResearchOrchestrator()

    await orchestrator._finalise(run_id, RunStatus.SUCCEEDED, "")
    await orchestrator._finalise(run_id, RunStatus.TIMED_OUT, "too late")

    async with session_scope() as session:
        run = await run_repo.get_run_unscoped(session, run_id)
        assert run is not None
        assert run.status == RunStatus.SUCCEEDED.value
        assert run.error == ""

        events = await run_repo.list_events(session, run_id)
        types = [event.type for event in events]
        assert EventType.RUN_SUCCEEDED.value in types
        assert EventType.RUN_TIMED_OUT.value not in types
