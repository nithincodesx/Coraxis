"""Run submission, quota enforcement, and API serialisation."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from coraxis.core.config import get_settings
from coraxis.core.errors import NotFoundError, QuotaExceededError
from coraxis.core.logging import get_logger
from coraxis.core.ratelimit import enforce
from coraxis.db.enums import EventLevel, EventType, RunStatus, RunTrigger
from coraxis.db.models import Run, User
from coraxis.repositories import runs as run_repo
from coraxis.repositories import teams as team_repo
from coraxis.schemas.runs import (
    ClaimOut,
    RunCreate,
    RunDetail,
    RunOut,
    RunStats,
    SourceOut,
)

logger = get_logger("runs")


async def submit(session: AsyncSession, user: User, payload: RunCreate) -> Run:
    """Create a run record after enforcing this user's quotas.

    Quotas are checked here rather than in the route so that every path into
    execution — API, retry, scheduled job — is subject to the same limits.
    """
    settings = get_settings()

    if payload.team_id is not None:
        team = await team_repo.get_team(session, user.id, payload.team_id)
        if team is None:
            raise NotFoundError("That team does not exist.")

    if settings.rate_limit_enabled:
        await enforce(
            f"run:{user.id}",
            limit=settings.rate_limit_runs_per_hour,
            window_seconds=3600,
            message=(
                f"You have reached the limit of {settings.rate_limit_runs_per_hour} "
                "research runs per hour."
            ),
        )

    active = await run_repo.count_active(session, user.id)
    if active >= settings.run_max_concurrent_per_user:
        raise QuotaExceededError(
            f"You already have {active} run(s) in progress. Wait for one to finish, or cancel it.",
            extra={"active_runs": active, "limit": settings.run_max_concurrent_per_user},
        )

    run = await run_repo.create_run(
        session,
        user.id,
        query=payload.query,
        trigger=RunTrigger.TEAM if payload.team_id else RunTrigger.PIPELINE,
        team_id=payload.team_id,
        options=payload.options.model_dump(),
    )

    await run_repo.add_event(
        session,
        run.id,
        type=EventType.RUN_QUEUED,
        level=EventLevel.INFO,
        message=f"Queued: {payload.query[:200]}",
    )

    logger.info("run %s queued for user %s", run.id, user.id)
    return run


async def retry(session: AsyncSession, user: User, run_id: str) -> Run:
    """Create a new run from a finished one, reusing its query and options."""
    original = await run_repo.get_run(session, user.id, run_id)
    if original is None:
        raise NotFoundError("Run not found.")
    if not original.is_terminal:
        raise QuotaExceededError("That run is still in progress.")

    payload = RunCreate.model_validate(
        {
            "query": original.query,
            "team_id": original.team_id,
            "options": original.options or {},
        }
    )
    new_run = await submit(session, user, payload)
    new_run.trigger = RunTrigger.RETRY.value
    await session.flush()
    return new_run


def to_run_out(run: Run) -> RunOut:
    """Map a run to its summary representation."""
    stats = _stats(run)
    return RunOut(
        id=run.id,
        query=run.query,
        status=_status(run.status),
        trigger=_trigger(run.trigger),
        team_id=run.team_id,
        error=run.error,
        options=dict(run.options or {}),
        stats=stats,
        executive_summary=run.executive_summary,
        key_findings=list(run.key_findings or []),
        source_count=stats.total_sources,
        claim_count=stats.total_claims,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        runtime_seconds=run.runtime_seconds,
    )


def to_run_detail(run: Run) -> RunDetail:
    """Map a run to its full representation, including evidence."""
    summary = to_run_out(run)
    return RunDetail(
        **summary.model_dump(),
        report_markdown=run.report_markdown,
        citations_markdown=run.citations_markdown,
        sources=[
            SourceOut(
                id=source.id,
                url=source.url,
                title=source.title,
                relevance=source.relevance,
                relevance_pct=source.relevance_pct,
                snippet=source.snippet,
                word_count=source.word_count,
                fetch_success=source.fetch_success,
            )
            for source in sorted(run.sources, key=lambda item: item.relevance, reverse=True)
        ],
        claims=[
            ClaimOut(
                id=claim.id,
                claim_ref=claim.claim_ref,
                text=claim.text,
                confidence=claim.confidence,
                relevance=claim.relevance,
                agent=claim.agent,
                source_urls=list(claim.source_urls or []),
            )
            for claim in run.claims
        ],
    )


def _stats(run: Run) -> RunStats:
    """Validate the stored stats blob, tolerating rows written by older code."""
    try:
        return RunStats.model_validate(run.stats or {})
    except Exception:  # noqa: BLE001 - never let a bad blob break a list endpoint
        logger.warning("run %s has unreadable stats; reporting zeros", run.id)
        return RunStats()


def _status(value: str) -> RunStatus:
    try:
        return RunStatus(value)
    except ValueError:
        logger.warning("unknown run status %r; reporting FAILED", value)
        return RunStatus.FAILED


def _trigger(value: str) -> RunTrigger:
    try:
        return RunTrigger(value)
    except ValueError:
        return RunTrigger.PIPELINE


def summarise(stats: dict[str, Any]) -> str:
    """One-line human summary of a run's outcome, for logs and the UI."""
    return (
        f"{stats.get('total_sources', 0)} sources, "
        f"{stats.get('total_claims', 0)} claims, "
        f"avg confidence {stats.get('avg_confidence', 0.0):.0%}"
    )
