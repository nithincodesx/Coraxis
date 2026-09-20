"""Startup work: seeding, recovery, and housekeeping."""

from __future__ import annotations

from coraxis.agents.definitions import definitions_with_tools
from coraxis.core.logging import get_logger
from coraxis.db.session import session_scope
from coraxis.repositories import agents as agent_repo
from coraxis.repositories import runs as run_repo
from coraxis.repositories import users as user_repo

logger = get_logger("bootstrap")


async def seed_builtin_agents() -> int:
    """Ensure the four built-in agents exist.

    Idempotent, so it runs on every boot. Existing rows are never overwritten —
    an operator who edited a prompt should not lose that edit to a redeploy.
    """
    async with session_scope() as session:
        created = await agent_repo.seed_builtin(session, definitions_with_tools())
    if created:
        logger.info("seeded %d built-in agent definition(s)", created)
    return created


async def recover_interrupted_runs() -> int:
    """Fail runs left mid-flight by a crash or hard restart.

    Without this, a run that was RUNNING when the process died would sit in
    that state forever and permanently consume the owner's concurrency quota.
    """
    async with session_scope() as session:
        reaped = await run_repo.reap_orphaned_runs(session)
    if reaped:
        logger.warning("marked %d interrupted run(s) as failed", reaped)
    return reaped


async def prune_expired_sessions() -> int:
    """Drop refresh-token rows that expired and were revoked over a week ago."""
    async with session_scope() as session:
        removed = await user_repo.delete_expired_sessions(session)
    if removed:
        logger.info("pruned %d expired session(s)", removed)
    return removed


async def run_startup_tasks() -> None:
    """Everything that must happen once, before the app serves traffic."""
    await seed_builtin_agents()
    await recover_interrupted_runs()
    await prune_expired_sessions()
