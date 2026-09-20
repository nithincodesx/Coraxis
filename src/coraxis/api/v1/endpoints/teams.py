"""Team endpoints."""

from __future__ import annotations

from fastapi import APIRouter, status

from coraxis.api.deps import CurrentUser, DbSession
from coraxis.core.errors import NotFoundError, ValidationError
from coraxis.repositories import agents as agent_repo
from coraxis.repositories import teams as team_repo
from coraxis.schemas.common import DeletedResponse
from coraxis.schemas.teams import TeamCreate, TeamOut, TeamStepOut, TeamUpdate

router = APIRouter(prefix="/teams", tags=["teams"])

#: Cap per user. Teams are cheap rows, but an unbounded list makes the UI unusable.
MAX_TEAMS = 50


def _to_out(team) -> TeamOut:
    return TeamOut(
        id=team.id,
        name=team.name,
        description=team.description,
        agent_slugs=[member.agent_slug for member in team.members],
        coordinator_slug=team.coordinator_slug,
        coordinator_instructions=team.coordinator_instructions,
        steps=[
            TeamStepOut(
                position=step.position,
                agent_slug=step.agent_slug,
                description=step.description,
                expected_output=step.expected_output,
            )
            for step in team.steps
        ],
        created_at=team.created_at,
        updated_at=team.updated_at,
    )


async def _check_agents_exist(session, user_id: str, slugs: list[str]) -> None:
    """Reject a team that references an agent the user cannot run.

    Better to fail at save time with a clear message than at run time halfway
    through a paid API call.
    """
    known = {definition.slug for definition in await agent_repo.list_definitions(session, user_id)}
    unknown = [slug for slug in slugs if slug not in known]
    if unknown:
        raise ValidationError(
            f"Unknown agent(s): {', '.join(unknown)}.",
            extra={"field": "agent_slugs", "unknown": unknown},
        )


@router.get("", response_model=list[TeamOut], summary="List teams")
async def list_teams(user: CurrentUser, session: DbSession) -> list[TeamOut]:
    return [_to_out(team) for team in await team_repo.list_teams(session, user.id)]


@router.get("/{team_id}", response_model=TeamOut, summary="Get one team")
async def get_team(team_id: str, user: CurrentUser, session: DbSession) -> TeamOut:
    team = await team_repo.get_team(session, user.id, team_id)
    if team is None:
        raise NotFoundError("Team not found.")
    return _to_out(team)


@router.post(
    "", response_model=TeamOut, status_code=status.HTTP_201_CREATED, summary="Create a team"
)
async def create_team(payload: TeamCreate, user: CurrentUser, session: DbSession) -> TeamOut:
    await _check_agents_exist(session, user.id, payload.agent_slugs)

    if payload.coordinator_slug and payload.coordinator_slug not in payload.agent_slugs:
        raise ValidationError(
            "The coordinator must be one of the team's agents.",
            extra={"field": "coordinator_slug"},
        )

    if await team_repo.count(session, user.id) >= MAX_TEAMS:
        raise ValidationError(f"You can create at most {MAX_TEAMS} teams.")

    team = await team_repo.create_team(session, user.id, payload)
    await session.commit()
    return _to_out(team)


@router.patch("/{team_id}", response_model=TeamOut, summary="Update a team")
async def update_team(
    team_id: str, payload: TeamUpdate, user: CurrentUser, session: DbSession
) -> TeamOut:
    team = await team_repo.get_team(session, user.id, team_id)
    if team is None:
        raise NotFoundError("Team not found.")

    if payload.agent_slugs is not None:
        await _check_agents_exist(session, user.id, payload.agent_slugs)

    coordinator = payload.coordinator_slug or team.coordinator_slug
    members = payload.agent_slugs or [member.agent_slug for member in team.members]
    if coordinator and coordinator not in members:
        raise ValidationError(
            "The coordinator must be one of the team's agents.",
            extra={"field": "coordinator_slug"},
        )

    team = await team_repo.update_team(session, team, payload)
    await session.commit()
    return _to_out(team)


@router.delete("/{team_id}", response_model=DeletedResponse, summary="Delete a team")
async def delete_team(team_id: str, user: CurrentUser, session: DbSession) -> DeletedResponse:
    team = await team_repo.get_team(session, user.id, team_id)
    if team is None:
        raise NotFoundError("Team not found.")

    await team_repo.delete_team(session, team)
    await session.commit()
    return DeletedResponse(deleted=True, id=team_id)
