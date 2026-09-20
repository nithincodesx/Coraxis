"""Agent definition and per-agent LLM settings persistence.

Built-in agent definitions live with ``user_id IS NULL`` and are shared by
everyone. The ``user_id == None`` comparisons below are deliberate: this is the
one place where "no owner" is a meaningful value rather than a bug.
"""

from __future__ import annotations

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from coraxis.db.enums import AgentKind
from coraxis.db.models import AgentDefinition, AgentLLMSettings
from coraxis.schemas.agents import AgentCreate, AgentLLMSettingsIn, AgentUpdate


async def list_definitions(session: AsyncSession, user_id: str) -> list[AgentDefinition]:
    """Built-in agents plus the user's own, ordered for display."""
    result = await session.execute(
        select(AgentDefinition)
        .where(or_(AgentDefinition.user_id.is_(None), AgentDefinition.user_id == user_id))
        .order_by(AgentDefinition.position, AgentDefinition.slug)
    )
    return list(result.scalars().all())


async def get_definition(session: AsyncSession, user_id: str, slug: str) -> AgentDefinition | None:
    """Fetch a built-in or owned agent by slug."""
    result = await session.execute(
        select(AgentDefinition).where(
            AgentDefinition.slug == slug,
            or_(AgentDefinition.user_id.is_(None), AgentDefinition.user_id == user_id),
        )
    )
    return result.scalar_one_or_none()


async def get_owned_definition(
    session: AsyncSession, user_id: str, slug: str
) -> AgentDefinition | None:
    """Fetch an agent the user may modify — never a built-in."""
    result = await session.execute(
        select(AgentDefinition).where(
            AgentDefinition.slug == slug,
            AgentDefinition.user_id == user_id,
            AgentDefinition.kind == AgentKind.CUSTOM.value,
        )
    )
    return result.scalar_one_or_none()


async def create_custom(
    session: AsyncSession, user_id: str, payload: AgentCreate
) -> AgentDefinition:
    definition = AgentDefinition(
        user_id=user_id,
        slug=payload.slug,
        name=payload.name,
        role=payload.role or payload.name,
        goal=payload.goal,
        backstory=payload.backstory,
        kind=AgentKind.CUSTOM.value,
        tools=list(payload.tools),
        position=100,  # after the built-ins
    )
    session.add(definition)
    await session.flush()
    return definition


async def update_custom(
    session: AsyncSession, definition: AgentDefinition, payload: AgentUpdate
) -> AgentDefinition:
    """Apply only the fields the caller actually sent."""
    changes = payload.model_dump(exclude_unset=True, exclude={"llm"})
    for field, value in changes.items():
        setattr(definition, field, value)
    await session.flush()
    return definition


async def delete_custom(session: AsyncSession, definition: AgentDefinition) -> None:
    await session.delete(definition)
    await session.flush()


async def count_custom(session: AsyncSession, user_id: str) -> int:
    result = await session.execute(
        select(AgentDefinition.id).where(
            AgentDefinition.user_id == user_id,
            AgentDefinition.kind == AgentKind.CUSTOM.value,
        )
    )
    return len(list(result.scalars().all()))


# ─── Per-agent LLM settings ──────────────────────────────────────────


async def list_llm_settings(session: AsyncSession, user_id: str) -> dict[str, AgentLLMSettings]:
    """All of a user's agent settings, keyed by agent slug."""
    result = await session.execute(
        select(AgentLLMSettings).where(AgentLLMSettings.user_id == user_id)
    )
    return {row.agent_slug: row for row in result.scalars().all()}


async def get_llm_settings(
    session: AsyncSession, user_id: str, agent_slug: str
) -> AgentLLMSettings | None:
    result = await session.execute(
        select(AgentLLMSettings).where(
            AgentLLMSettings.user_id == user_id,
            AgentLLMSettings.agent_slug == agent_slug,
        )
    )
    return result.scalar_one_or_none()


async def upsert_llm_settings(
    session: AsyncSession,
    user_id: str,
    agent_slug: str,
    payload: AgentLLMSettingsIn,
) -> AgentLLMSettings:
    settings_row = await get_llm_settings(session, user_id, agent_slug)
    if settings_row is None:
        settings_row = AgentLLMSettings(user_id=user_id, agent_slug=agent_slug)
        session.add(settings_row)

    settings_row.provider = payload.provider
    settings_row.model = payload.model
    settings_row.temperature = payload.temperature
    settings_row.max_tokens = payload.max_tokens
    settings_row.base_url = payload.base_url

    await session.flush()
    return settings_row


async def delete_llm_settings(session: AsyncSession, user_id: str, agent_slug: str) -> bool:
    settings_row = await get_llm_settings(session, user_id, agent_slug)
    if settings_row is None:
        return False
    await session.delete(settings_row)
    await session.flush()
    return True


async def seed_builtin(
    session: AsyncSession,
    definitions: list[dict[str, object]],
) -> int:
    """Insert built-in agent rows that do not exist yet.

    Idempotent: safe to call on every startup. Existing rows are left alone so
    a prompt tweak made by hand is not clobbered by a redeploy.
    """
    result = await session.execute(
        select(AgentDefinition.slug).where(
            AgentDefinition.user_id.is_(None),
            AgentDefinition.kind == AgentKind.BUILTIN.value,
        )
    )
    existing = set(result.scalars().all())

    created = 0
    for position, definition in enumerate(definitions):
        slug = str(definition["slug"])
        if slug in existing:
            continue

        # The definitions come from a module-level literal, so mypy sees the
        # values as `object`. Narrowing here keeps a malformed entry from
        # crashing seeding at import time.
        raw_tools = definition.get("tools")
        tools = [str(tool) for tool in raw_tools] if isinstance(raw_tools, list | tuple) else []

        session.add(
            AgentDefinition(
                user_id=None,
                slug=slug,
                name=str(definition["name"]),
                role=str(definition["role"]),
                goal=str(definition["goal"]),
                backstory=str(definition["backstory"]),
                kind=AgentKind.BUILTIN.value,
                tools=tools,
                position=position,
            )
        )
        created += 1

    if created:
        await session.flush()
    return created
