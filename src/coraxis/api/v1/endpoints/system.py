"""Health, readiness, and metrics endpoints.

These are mounted twice: once at the application root (``/health``) so that
orchestrators and container probes find them at the conventional path, and once
under ``/api/v1`` for the frontend.
"""

from __future__ import annotations

import time

from fastapi import APIRouter
from sqlalchemy import text

from coraxis import __version__
from coraxis.api.deps import CurrentUser, DbSession
from coraxis.core.config import get_settings
from coraxis.repositories import runs as run_repo
from coraxis.schemas.common import HealthResponse, ReadyCheck, ReadyResponse
from coraxis.services.events import event_bus
from coraxis.workers import run_runner

router = APIRouter(tags=["system"])

#: Recorded at import so uptime reflects process age, not request age.
_STARTED_AT = time.monotonic()


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health() -> HealthResponse:
    """Is the process up?

    Deliberately touches no dependency: a slow database must not cause an
    orchestrator to kill an otherwise healthy container. Use ``/ready`` for
    that decision.
    """
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        version=__version__,
        environment=settings.env,
        uptime_seconds=round(time.monotonic() - _STARTED_AT, 2),
    )


@router.get("/ready", response_model=ReadyResponse, summary="Readiness probe")
async def ready(session: DbSession) -> ReadyResponse:
    """Can this instance serve traffic?

    Checks every hard dependency. Returns 200 with ``ready: false`` rather than
    a 5xx so a probe can distinguish "not ready yet" from "broken".
    """
    checks: list[ReadyCheck] = []

    try:
        await session.execute(text("SELECT 1"))
        checks.append(ReadyCheck(name="database", ok=True))
    except Exception as exc:  # noqa: BLE001 - the probe reports, it does not raise
        checks.append(ReadyCheck(name="database", ok=False, detail=str(exc)[:200]))

    settings = get_settings()
    configured = [
        provider
        for provider in ("groq", "gemini", "openai")
        if settings.providers.key_for(provider)
    ]
    checks.append(
        ReadyCheck(
            name="providers",
            ok=True,  # a missing key is a user problem, not an instance problem
            detail=(
                f"Environment fallback keys: {', '.join(configured)}"
                if configured
                else "No environment fallback keys. Users must supply their own."
            ),
        )
    )

    checks.append(
        ReadyCheck(
            name="runner",
            ok=True,
            detail=f"{run_runner.active_count} run(s) in flight",
        )
    )

    return ReadyResponse(ready=all(check.ok for check in checks), checks=checks)


@router.get("/metrics", summary="Usage metrics")
async def metrics(user: CurrentUser, session: DbSession) -> dict:
    """Per-account usage totals.

    Authenticated on purpose: aggregate counts and confidence averages are the
    user's data, not public information about the instance.
    """
    stats = await run_repo.aggregate_stats(session, user.id)
    return {
        **stats,
        "active_runs": run_runner.active_count,
        "stream_subscribers": event_bus.subscriber_count(""),
        "uptime_seconds": round(time.monotonic() - _STARTED_AT, 2),
        "version": __version__,
    }


@router.get("/version", summary="Version information")
async def version() -> dict:
    settings = get_settings()
    return {
        "version": __version__,
        "environment": settings.env,
        "api_version": "v1",
    }
