"""Run endpoints, including the live progress stream."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Header, Query, Request, status
from fastapi.responses import Response, StreamingResponse

from coraxis.api.deps import CurrentUser, DbSession, PaginationDep
from coraxis.core.errors import NotFoundError
from coraxis.db.enums import RunStatus
from coraxis.db.session import session_scope
from coraxis.repositories import runs as run_repo
from coraxis.schemas.common import DeletedResponse, Page
from coraxis.schemas.runs import (
    RunAccepted,
    RunCreate,
    RunDetail,
    RunEventOut,
    RunOut,
)
from coraxis.services import runs as run_service
from coraxis.services.events import event_bus
from coraxis.workers import run_runner

router = APIRouter(prefix="/runs", tags=["runs"])

#: Event types that mean the run is over and the stream can close.
_TERMINAL_EVENTS = frozenset(
    {
        "run.succeeded",
        "run.failed",
        "run.cancelled",
        "run.timed_out",
    }
)

#: Seconds between keepalive comments on an idle stream. Without these, proxies
#: close an apparently-dead connection.
_KEEPALIVE_SECONDS = 15.0

#: Replay cap on reconnect. A client that was away for a very long run gets the
#: tail rather than the entire history in one response.
_MAX_REPLAY = 1000


def _sse(event: dict) -> str:
    """Format one server-sent event."""
    payload = json.dumps(event, ensure_ascii=False, default=str)
    return f"id: {event.get('seq', 0)}\nevent: {event.get('type', 'message')}\ndata: {payload}\n\n"


@router.post(
    "",
    response_model=RunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Submit a research run",
)
async def submit_run(payload: RunCreate, user: CurrentUser, session: DbSession) -> RunAccepted:
    """Queue a run.

    Returns ``202`` with the run id and a stream URL. The work happens in the
    background; poll the run or subscribe to the stream for progress.
    """
    run = await run_service.submit(session, user, payload)
    await session.commit()

    run_runner.submit(run.id)

    return RunAccepted(
        run_id=run.id,
        status=RunStatus(run.status),
        stream_url=f"/api/v1/runs/{run.id}/stream",
        detail_url=f"/api/v1/runs/{run.id}",
    )


@router.get("", response_model=Page[RunOut], summary="List runs")
async def list_runs(
    user: CurrentUser,
    session: DbSession,
    pagination: PaginationDep,
    run_status: RunStatus | None = Query(default=None, alias="status"),
    team_id: str | None = Query(default=None),
) -> Page[RunOut]:
    rows, total = await run_repo.list_runs(
        session,
        user.id,
        status=run_status,
        team_id=team_id,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return Page[RunOut](
        items=[run_service.to_run_out(run) for run in rows],
        total=total,
        limit=pagination.limit,
        offset=pagination.offset,
    )


@router.get("/{run_id}", response_model=RunDetail, summary="Get a run")
async def get_run(run_id: str, user: CurrentUser, session: DbSession) -> RunDetail:
    run = await run_repo.get_run(session, user.id, run_id)
    if run is None:
        raise NotFoundError("Run not found.")
    return run_service.to_run_detail(run)


@router.get(
    "/{run_id}/report.md",
    summary="Download the report as markdown",
    response_class=Response,
)
async def download_report(run_id: str, user: CurrentUser, session: DbSession) -> Response:
    run = await run_repo.get_run(session, user.id, run_id)
    if run is None:
        raise NotFoundError("Run not found.")
    if not run.report_markdown:
        raise NotFoundError("This run has no report yet.")

    filename = f"coraxis-{run_id[:8]}.md"
    return Response(
        content=run.report_markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{run_id}/cancel", response_model=RunOut, summary="Cancel a run")
async def cancel_run(run_id: str, user: CurrentUser, session: DbSession) -> RunOut:
    """Request cancellation.

    Cooperative: the worker checks the flag between agent steps, so the run
    stops within a few seconds rather than instantly. A run that already
    finished returns its final state unchanged.
    """
    run = await run_repo.get_run(session, user.id, run_id)
    if run is None:
        raise NotFoundError("Run not found.")

    await run_repo.request_cancel(session, run)
    await session.commit()
    await session.refresh(run)
    return run_service.to_run_out(run)


@router.post(
    "/{run_id}/retry",
    response_model=RunAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-run a finished run",
)
async def retry_run(run_id: str, user: CurrentUser, session: DbSession) -> RunAccepted:
    new_run = await run_service.retry(session, user, run_id)
    await session.commit()

    run_runner.submit(new_run.id)

    return RunAccepted(
        run_id=new_run.id,
        status=RunStatus(new_run.status),
        stream_url=f"/api/v1/runs/{new_run.id}/stream",
        detail_url=f"/api/v1/runs/{new_run.id}",
    )


@router.delete("/{run_id}", response_model=DeletedResponse, summary="Delete a run")
async def delete_run(run_id: str, user: CurrentUser, session: DbSession) -> DeletedResponse:
    run = await run_repo.get_run(session, user.id, run_id)
    if run is None:
        raise NotFoundError("Run not found.")

    if not run.is_terminal:
        await run_repo.request_cancel(session, run)

    await run_repo.delete_run(session, run)
    await session.commit()
    return DeletedResponse(deleted=True, id=run_id)


@router.get(
    "/{run_id}/events",
    response_model=list[RunEventOut],
    summary="Get a run's timeline",
)
async def list_events(
    run_id: str,
    user: CurrentUser,
    session: DbSession,
    since: int = Query(default=0, ge=0, description="Return events after this sequence number."),
    limit: int = Query(default=500, ge=1, le=2000),
) -> list[RunEventOut]:
    """Polling fallback for clients that cannot hold an SSE connection open."""
    run = await run_repo.get_run(session, user.id, run_id)
    if run is None:
        raise NotFoundError("Run not found.")

    events = await run_repo.list_events(session, run_id, since_seq=since, limit=limit)
    return [RunEventOut.model_validate(event) for event in events]


@router.get("/{run_id}/stream", summary="Stream a run's progress (SSE)")
async def stream_run(
    run_id: str,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    since: int = Query(default=0, ge=0),
) -> StreamingResponse:
    """Server-sent events for one run.

    On reconnect, send ``Last-Event-ID`` (browsers do this automatically) or
    ``?since=`` to receive only the events you missed. Because every event is
    persisted with a monotonic sequence number before it is broadcast, the
    replay is exact and gap-free.
    """
    run = await run_repo.get_run(session, user.id, run_id)
    if run is None:
        raise NotFoundError("Run not found.")

    try:
        cursor = int(last_event_id) if last_event_id else since
    except (TypeError, ValueError):
        cursor = since

    async def generate() -> AsyncIterator[str]:
        nonlocal cursor

        # ── Replay ───────────────────────────────────────────────────
        async with session_scope() as replay_session:
            missed = await run_repo.list_events(
                replay_session, run_id, since_seq=cursor, limit=_MAX_REPLAY
            )
            current = await run_repo.get_run_unscoped(replay_session, run_id)

        for event in missed:
            cursor = max(cursor, event.seq)
            yield _sse(
                {
                    "id": event.id,
                    "seq": event.seq,
                    "type": event.type,
                    "agent": event.agent,
                    "level": event.level,
                    "message": event.message,
                    "payload": event.payload,
                    "created_at": event.created_at.isoformat() + "Z",
                }
            )

        if current is None or RunStatus(current.status).is_terminal:
            yield _sse({"seq": cursor, "type": "stream.closed", "payload": {"reason": "terminal"}})
            return

        # ── Live ─────────────────────────────────────────────────────
        async with event_bus.subscription(run_id) as queue:
            while True:
                if await request.is_disconnected():
                    return

                try:
                    live_event = await asyncio.wait_for(queue.get(), timeout=_KEEPALIVE_SECONDS)
                except TimeoutError:
                    # Comment frame: keeps intermediaries from closing the socket.
                    yield ": keepalive\n\n"
                    continue

                # Deliberately a separate name from the replay loop's `event`:
                # that one is an ORM row, this one is the dict the bus carries.
                if int(live_event.get("seq", 0)) <= cursor:
                    continue  # already replayed

                cursor = int(live_event.get("seq", cursor))
                yield _sse(live_event)

                if live_event.get("type") in _TERMINAL_EVENTS:
                    return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            # Tells nginx not to buffer, which would defeat streaming entirely.
            "X-Accel-Buffering": "no",
        },
    )
