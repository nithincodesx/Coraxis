"""Agent definition endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status

from coraxis.agents.tool_registry import TOOL_REGISTRY, validate_tool_ids
from coraxis.api.deps import CurrentUser, DbSession
from coraxis.core.errors import ConflictError, NotFoundError, ValidationError
from coraxis.db.enums import DEFAULT_MODELS, AgentKind
from coraxis.db.models import AgentDefinition
from coraxis.repositories import agents as agent_repo
from coraxis.repositories import teams as team_repo
from coraxis.schemas.agents import (
    AgentCatalog,
    AgentCreate,
    AgentLLMSettingsIn,
    AgentLLMSettingsOut,
    AgentOut,
    AgentUpdate,
    ToolOut,
)
from coraxis.schemas.common import DeletedResponse

router = APIRouter(prefix="/agents", tags=["agents"])

#: Cap on custom agents per user. Stops an unbounded agent list from becoming
#: an unbounded prompt-building cost.
MAX_CUSTOM_AGENTS = 25


def _llm_out(settings_row: Any | None) -> AgentLLMSettingsOut:
    """Per-agent LLM settings, with sensible defaults when unset."""
    if settings_row is None:
        return AgentLLMSettingsOut(
            provider="groq",
            model="",
            temperature=0.2,
            max_tokens=4096,
            base_url="",
        )
    return AgentLLMSettingsOut(
        provider=settings_row.provider,
        model=settings_row.model,
        temperature=settings_row.temperature,
        max_tokens=settings_row.max_tokens,
        base_url=settings_row.base_url,
    )


def _to_out(definition: AgentDefinition, settings_row: Any | None) -> AgentOut:
    return AgentOut(
        id=definition.id,
        slug=definition.slug,
        name=definition.name,
        role=definition.role,
        goal=definition.goal,
        backstory=definition.backstory,
        kind=AgentKind(definition.kind),
        tools=list(definition.tools or []),
        position=definition.position,
        is_builtin=definition.is_builtin,
        llm=_llm_out(settings_row),
        created_at=definition.created_at,
        updated_at=definition.updated_at,
    )


@router.get("", response_model=AgentCatalog, summary="List agents and available tools")
async def list_agents(user: CurrentUser, session: DbSession) -> AgentCatalog:
    """Everything the agent builder needs in one round trip."""
    definitions = await agent_repo.list_definitions(session, user.id)
    settings = await agent_repo.list_llm_settings(session, user.id)

    return AgentCatalog(
        agents=[_to_out(definition, settings.get(definition.slug)) for definition in definitions],
        tools=[
            ToolOut(
                id=spec.id,
                label=spec.label,
                description=spec.description,
                requires_tracker=spec.requires_tracker,
            )
            for spec in TOOL_REGISTRY.values()
        ],
    )


@router.get("/{slug}", response_model=AgentOut, summary="Get one agent")
async def get_agent(slug: str, user: CurrentUser, session: DbSession) -> AgentOut:
    definition = await agent_repo.get_definition(session, user.id, slug)
    if definition is None:
        raise NotFoundError(f"No agent with slug '{slug}'.")
    settings_row = await agent_repo.get_llm_settings(session, user.id, slug)
    return _to_out(definition, settings_row)


@router.post(
    "",
    response_model=AgentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a custom agent",
)
async def create_agent(payload: AgentCreate, user: CurrentUser, session: DbSession) -> AgentOut:
    unknown = validate_tool_ids(payload.tools)
    if unknown:
        raise ValidationError(
            f"Unknown tool id(s): {', '.join(unknown)}.",
            extra={"field": "tools", "unknown": unknown},
        )

    if await agent_repo.get_definition(session, user.id, payload.slug) is not None:
        raise ConflictError(f"An agent with slug '{payload.slug}' already exists.")

    if await agent_repo.count_custom(session, user.id) >= MAX_CUSTOM_AGENTS:
        raise ConflictError(f"You can create at most {MAX_CUSTOM_AGENTS} custom agents.")

    definition = await agent_repo.create_custom(session, user.id, payload)
    settings_row = await agent_repo.upsert_llm_settings(
        session, user.id, definition.slug, payload.llm
    )
    await session.commit()
    return _to_out(definition, settings_row)


@router.patch("/{slug}", response_model=AgentOut, summary="Update a custom agent")
async def update_agent(
    slug: str, payload: AgentUpdate, user: CurrentUser, session: DbSession
) -> AgentOut:
    """Built-in agents are read-only. Clone one by POSTing it under a new slug."""
    definition = await agent_repo.get_owned_definition(session, user.id, slug)
    if definition is None:
        builtin = await agent_repo.get_definition(session, user.id, slug)
        if builtin is not None and builtin.is_builtin:
            raise ValidationError(
                "Built-in agents cannot be modified. Create a custom agent with the "
                "same settings instead.",
                extra={"field": "slug"},
            )
        raise NotFoundError(f"No custom agent with slug '{slug}'.")

    if payload.tools is not None:
        unknown = validate_tool_ids(payload.tools)
        if unknown:
            raise ValidationError(
                f"Unknown tool id(s): {', '.join(unknown)}.",
                extra={"field": "tools", "unknown": unknown},
            )

    await agent_repo.update_custom(session, definition, payload)
    settings_row = await agent_repo.get_llm_settings(session, user.id, slug)
    if payload.llm is not None:
        settings_row = await agent_repo.upsert_llm_settings(session, user.id, slug, payload.llm)

    await session.commit()
    return _to_out(definition, settings_row)


@router.put(
    "/{slug}/llm",
    response_model=AgentOut,
    summary="Set an agent's model configuration",
)
async def set_agent_llm(
    slug: str, payload: AgentLLMSettingsIn, user: CurrentUser, session: DbSession
) -> AgentOut:
    """Works for built-in agents too — the model is per user, the role is shared."""
    definition = await agent_repo.get_definition(session, user.id, slug)
    if definition is None:
        raise NotFoundError(f"No agent with slug '{slug}'.")

    settings_row = await agent_repo.upsert_llm_settings(session, user.id, slug, payload)
    await session.commit()
    return _to_out(definition, settings_row)


@router.delete("/{slug}", response_model=DeletedResponse, summary="Delete a custom agent")
async def delete_agent(slug: str, user: CurrentUser, session: DbSession) -> DeletedResponse:
    definition = await agent_repo.get_owned_definition(session, user.id, slug)
    if definition is None:
        raise NotFoundError("No custom agent with that slug. Built-in agents cannot be deleted.")

    # Detach the agent from any team that referenced it, rather than leaving a
    # dangling slug that fails at run time.
    await team_repo.remove_agent_from_teams(session, user.id, slug)
    await agent_repo.delete_llm_settings(session, user.id, slug)
    await agent_repo.delete_custom(session, definition)
    await session.commit()
    return DeletedResponse(deleted=True, id=slug)


@router.get(
    "/{slug}/defaults",
    response_model=AgentLLMSettingsOut,
    summary="Suggested model for an agent",
)
async def agent_defaults(slug: str, provider: str = "groq") -> AgentLLMSettingsOut:
    """The default model for a provider, so the UI can pre-fill the form."""
    return AgentLLMSettingsOut(
        provider=provider,  # type: ignore[arg-type]
        model=DEFAULT_MODELS.get(provider, ""),
        temperature=0.2,
        max_tokens=4096,
        base_url="",
    )
