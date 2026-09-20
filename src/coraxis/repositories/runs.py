"""Run, event, source, and claim persistence.

Event sequence numbers are allocated with an atomic ``UPDATE ... RETURNING``
rather than a read-then-write, so two writers can never mint the same ``seq``.
SQLite has supported ``RETURNING`` since 3.35 (2021) and every supported
Postgres version has it.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from coraxis.core.errors import NotFoundError
from coraxis.db.base import utcnow
from coraxis.db.enums import EventLevel, EventType, RunStatus, RunTrigger
from coraxis.db.models import Run, RunClaim, RunEvent, RunSource

# ─── Runs ────────────────────────────────────────────────────────────


async def create_run(
    session: AsyncSession,
    user_id: str,
    *,
    query: str,
    trigger: RunTrigger = RunTrigger.PIPELINE,
    team_id: str | None = None,
    options: dict[str, Any] | None = None,
) -> Run:
    run = Run(
        user_id=user_id,
        query=query,
        trigger=trigger.value,
        team_id=team_id,
        status=RunStatus.QUEUED.value,
        options=options or {},
    )
    session.add(run)
    await session.flush()
    return run


async def get_run(session: AsyncSession, user_id: str, run_id: str) -> Run | None:
    """Fetch a run scoped to its owner."""
    result = await session.execute(select(Run).where(Run.id == run_id, Run.user_id == user_id))
    return result.scalar_one_or_none()


async def get_run_unscoped(session: AsyncSession, run_id: str) -> Run | None:
    """Fetch a run without an ownership filter.

    Only for background workers, which act on behalf of the system rather than
    a request. Never call this from a route handler.
    """
    return await session.get(Run, run_id)


async def list_runs(
    session: AsyncSession,
    user_id: str,
    *,
    status: RunStatus | None = None,
    team_id: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> tuple[list[Run], int]:
    """Return one page of runs plus the total matching count."""
    filters = [Run.user_id == user_id]
    if status is not None:
        filters.append(Run.status == status.value)
    if team_id is not None:
        filters.append(Run.team_id == team_id)

    total = await session.execute(select(func.count()).select_from(Run).where(*filters))

    result = await session.execute(
        select(Run).where(*filters).order_by(Run.created_at.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all()), int(total.scalar_one())


async def mark_started(session: AsyncSession, run: Run) -> None:
    run.status = RunStatus.RUNNING.value
    run.started_at = utcnow()
    run.error = ""
    await session.flush()


async def mark_finished(
    session: AsyncSession,
    run: Run,
    *,
    status: RunStatus,
    error: str = "",
) -> None:
    """Write the terminal state exactly once.

    Guards against a late timeout clobbering a run that already succeeded.
    """
    if run.is_terminal:
        return

    run.status = status.value
    run.finished_at = utcnow()
    run.error = error[:4000]
    if run.started_at is not None:
        run.runtime_seconds = round((run.finished_at - run.started_at).total_seconds(), 3)
    await session.flush()


async def attach_report(
    session: AsyncSession,
    run: Run,
    *,
    report_markdown: str,
    executive_summary: str = "",
    key_findings: list[str] | None = None,
    citations_markdown: str = "",
    stats: dict[str, Any] | None = None,
) -> None:
    run.report_markdown = report_markdown
    run.executive_summary = executive_summary
    run.key_findings = key_findings or []
    run.citations_markdown = citations_markdown
    if stats:
        run.stats = {**(run.stats or {}), **stats}
    await session.flush()


async def request_cancel(session: AsyncSession, run: Run) -> bool:
    """Flag a run for cooperative cancellation.

    Returns ``False`` if the run already finished, so the caller can report an
    honest "too late" instead of pretending the cancel worked.
    """
    if run.is_terminal:
        return False
    run.cancel_requested = True
    await session.flush()
    return True


async def is_cancel_requested(session: AsyncSession, run_id: str) -> bool:
    """Re-read the cancel flag.

    Deliberately a fresh query rather than a cached attribute: the worker may
    hold a stale ORM instance while the user clicks Cancel in another request.
    """
    result = await session.execute(select(Run.cancel_requested).where(Run.id == run_id))
    return bool(result.scalar_one_or_none())


async def count_active(session: AsyncSession, user_id: str) -> int:
    """Runs queued or running for a user — the input to the concurrency quota."""
    result = await session.execute(
        select(func.count())
        .select_from(Run)
        .where(
            Run.user_id == user_id,
            Run.status.in_([RunStatus.QUEUED.value, RunStatus.RUNNING.value]),
        )
    )
    return int(result.scalar_one())


async def delete_run(session: AsyncSession, run: Run) -> None:
    await session.delete(run)
    await session.flush()


async def reap_orphaned_runs(session: AsyncSession) -> int:
    """Fail runs left mid-flight by a crash or hard restart.

    Called once at startup. Without this, a run that was RUNNING when the
    process died would sit in that state forever and permanently consume the
    user's concurrency quota.
    """
    result = await session.execute(
        select(Run).where(Run.status.in_([RunStatus.QUEUED.value, RunStatus.RUNNING.value]))
    )
    orphans = list(result.scalars().all())
    for run in orphans:
        run.status = RunStatus.FAILED.value
        run.error = "Interrupted by a server restart."
        run.finished_at = utcnow()
    if orphans:
        await session.flush()
    return len(orphans)


# ─── Events ──────────────────────────────────────────────────────────


async def next_event_seq(session: AsyncSession, run_id: str) -> int:
    """Atomically reserve the next sequence number for a run."""
    result = await session.execute(
        update(Run)
        .where(Run.id == run_id)
        .values(event_seq=Run.event_seq + 1)
        .returning(Run.event_seq)
    )
    seq = result.scalar_one_or_none()
    if seq is None:
        raise NotFoundError(f"Run {run_id} not found while allocating an event sequence.")
    return int(seq)


async def add_event(
    session: AsyncSession,
    run_id: str,
    *,
    type: EventType,
    agent: str = "",
    level: EventLevel = EventLevel.INFO,
    message: str = "",
    payload: dict[str, Any] | None = None,
) -> RunEvent:
    """Append one event to a run's timeline."""
    seq = await next_event_seq(session, run_id)
    event = RunEvent(
        run_id=run_id,
        seq=seq,
        type=type.value,
        agent=agent,
        level=level.value,
        message=message[:4000],
        payload=payload or {},
    )
    session.add(event)
    await session.flush()
    return event


async def list_events(
    session: AsyncSession,
    run_id: str,
    *,
    since_seq: int = 0,
    limit: int = 500,
) -> list[RunEvent]:
    """Events after ``since_seq``, oldest first.

    This is the SSE replay path: ``since_seq`` comes straight from the client's
    ``Last-Event-ID`` header, so a reconnect resumes rather than restarts.
    """
    result = await session.execute(
        select(RunEvent)
        .where(RunEvent.run_id == run_id, RunEvent.seq > since_seq)
        .order_by(RunEvent.seq)
        .limit(limit)
    )
    return list(result.scalars().all())


# ─── Sources and claims ──────────────────────────────────────────────


async def replace_sources(
    session: AsyncSession,
    run_id: str,
    sources: list[dict[str, Any]],
) -> int:
    """Replace a run's source set.

    Delete-then-insert rather than a diff: the citation tracker re-scores
    sources as the pipeline progresses, so an upsert keyed on URL would still
    have to rewrite every relevance value.
    """
    await session.execute(delete(RunSource).where(RunSource.run_id == run_id))

    rows = [
        RunSource(
            run_id=run_id,
            url=str(source.get("url", "")),
            title=str(source.get("title", "")),
            relevance=float(source.get("relevance", 0.0)),
            snippet=str(source.get("snippet", ""))[:2000],
            word_count=int(source.get("word_count", 0)),
            fetch_success=bool(source.get("fetch_success", False)),
        )
        for source in sources
        if source.get("url")
    ]
    session.add_all(rows)
    await session.flush()
    return len(rows)


async def replace_claims(
    session: AsyncSession,
    run_id: str,
    claims: list[dict[str, Any]],
) -> int:
    await session.execute(delete(RunClaim).where(RunClaim.run_id == run_id))

    rows = [
        RunClaim(
            run_id=run_id,
            claim_ref=str(claim.get("claim_ref", "")),
            text=str(claim.get("text", "")),
            confidence=float(claim.get("confidence", 0.0)),
            relevance=float(claim.get("relevance", 0.0)),
            agent=str(claim.get("agent", "")),
            source_urls=list(claim.get("source_urls", [])),
        )
        for claim in claims
        if claim.get("text")
    ]
    session.add_all(rows)
    await session.flush()
    return len(rows)


# ─── Aggregates ──────────────────────────────────────────────────────


async def aggregate_stats(session: AsyncSession, user_id: str) -> dict[str, Any]:
    """Account-level totals, computed in SQL rather than by loading rows."""
    runs_total = await session.execute(
        select(func.count()).select_from(Run).where(Run.user_id == user_id)
    )
    by_status = await session.execute(
        select(Run.status, func.count()).where(Run.user_id == user_id).group_by(Run.status)
    )
    sources_total = await session.execute(
        select(func.count()).select_from(RunSource).join(Run).where(Run.user_id == user_id)
    )
    claims_total = await session.execute(
        select(func.count()).select_from(RunClaim).join(Run).where(Run.user_id == user_id)
    )
    avg_confidence = await session.execute(
        select(func.avg(RunClaim.confidence)).join(Run).where(Run.user_id == user_id)
    )
    avg_relevance = await session.execute(
        select(func.avg(RunSource.relevance)).join(Run).where(Run.user_id == user_id)
    )
    runtime = await session.execute(
        select(func.sum(Run.runtime_seconds)).where(Run.user_id == user_id)
    )

    return {
        "total_runs": int(runs_total.scalar_one()),
        "runs_by_status": {status: int(count) for status, count in by_status.all()},
        "total_sources_analyzed": int(sources_total.scalar_one()),
        "total_claims_synthesized": int(claims_total.scalar_one()),
        "avg_confidence": round(float(avg_confidence.scalar_one() or 0.0), 4),
        "avg_relevance": round(float(avg_relevance.scalar_one() or 0.0), 4),
        "total_runtime_seconds": round(float(runtime.scalar_one() or 0.0), 2),
    }
