"""Team persistence.

Members and steps are stored as ordered child rows rather than a JSON blob so
that "which teams use agent X?" is a join rather than a scan, and so deleting a
custom agent can cascade correctly.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from coraxis.db.models import Team, TeamMember, TeamStep
from coraxis.schemas.teams import TeamCreate, TeamUpdate


async def list_teams(session: AsyncSession, user_id: str) -> list[Team]:
    result = await session.execute(
        select(Team).where(Team.user_id == user_id).order_by(Team.created_at.desc())
    )
    return list(result.scalars().all())


async def get_team(session: AsyncSession, user_id: str, team_id: str) -> Team | None:
    """Fetch a team, scoped to its owner.

    The ``user_id`` predicate is the authorisation check — a team belonging to
    someone else is indistinguishable from one that does not exist.
    """
    result = await session.execute(select(Team).where(Team.id == team_id, Team.user_id == user_id))
    return result.scalar_one_or_none()


async def count(session: AsyncSession, user_id: str) -> int:
    result = await session.execute(
        select(func.count()).select_from(Team).where(Team.user_id == user_id)
    )
    return int(result.scalar_one())


def _apply_members(team: Team, slugs: list[str]) -> None:
    """Replace membership, preserving the caller's ordering."""
    team.members.clear()
    for position, slug in enumerate(slugs):
        team.members.append(TeamMember(agent_slug=slug, position=position))


def _apply_steps(team: Team, steps: list) -> None:
    team.steps.clear()
    for position, step in enumerate(steps):
        team.steps.append(
            TeamStep(
                position=position,
                agent_slug=step.agent_slug,
                description=step.description,
                expected_output=step.expected_output,
            )
        )


async def create_team(session: AsyncSession, user_id: str, payload: TeamCreate) -> Team:
    team = Team(
        user_id=user_id,
        name=payload.name,
        description=payload.description,
        coordinator_slug=payload.coordinator_slug,
        coordinator_instructions=payload.coordinator_instructions,
    )
    _apply_members(team, payload.agent_slugs)
    _apply_steps(team, payload.steps)

    session.add(team)
    await session.flush()
    await session.refresh(team, attribute_names=["members", "steps"])
    return team


async def update_team(session: AsyncSession, team: Team, payload: TeamUpdate) -> Team:
    """Apply a partial update. Collections are replaced only when supplied."""
    if payload.name is not None:
        team.name = payload.name
    if payload.description is not None:
        team.description = payload.description
    if payload.coordinator_slug is not None:
        team.coordinator_slug = payload.coordinator_slug or None
    if payload.coordinator_instructions is not None:
        team.coordinator_instructions = payload.coordinator_instructions
    if payload.agent_slugs is not None:
        _apply_members(team, payload.agent_slugs)
    if payload.steps is not None:
        _apply_steps(team, payload.steps)

    await session.flush()
    await session.refresh(team, attribute_names=["members", "steps"])
    return team


async def delete_team(session: AsyncSession, team: Team) -> None:
    await session.delete(team)
    await session.flush()


async def remove_agent_from_teams(session: AsyncSession, user_id: str, agent_slug: str) -> int:
    """Detach a deleted agent from every team that referenced it.

    Without this, a team would keep a dangling slug and fail at run time with a
    confusing error instead of quietly shrinking.
    """
    result = await session.execute(
        select(TeamMember)
        .join(Team)
        .where(
            Team.user_id == user_id,
            TeamMember.agent_slug == agent_slug,
        )
    )
    members = list(result.scalars().all())
    for member in members:
        await session.delete(member)
    if members:
        await session.flush()
    return len(members)
