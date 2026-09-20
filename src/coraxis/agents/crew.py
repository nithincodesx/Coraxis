"""Crew assembly.

Two entry points: :func:`build_pipeline_crew` for the built-in four-agent
pipeline, and :func:`build_team_crew` for a user-composed team. Both take
already-resolved agent definitions and LLM configs — nothing here reads the
database or the environment.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from crewai import Agent, Crew, Process

from coraxis.agents.context import ToolContext
from coraxis.agents.tasks import build_pipeline_tasks, build_team_tasks
from coraxis.agents.tool_registry import ALWAYS_AVAILABLE, TOOL_REGISTRY
from coraxis.core.errors import ConfigurationError
from coraxis.core.logging import get_logger
from coraxis.services.llm.factory import LLMConfig, build_llm

logger = get_logger("crew")


@dataclass(frozen=True, slots=True)
class AgentSpec:
    """An agent definition paired with the LLM that should run it."""

    slug: str
    name: str
    role: str
    goal: str
    backstory: str
    tools: tuple[str, ...]
    llm: LLMConfig

    @property
    def display_role(self) -> str:
        return self.role or self.name


def build_tools(tool_ids: Iterable[str], context: ToolContext) -> list[Any]:
    """Instantiate the requested tools, skipping unknown ids.

    An unknown id is logged rather than fatal: a tool removed in an upgrade
    should degrade an old saved agent, not break it.
    """
    tools: list[Any] = []
    seen: set[str] = set()

    for tool_id in list(tool_ids) + list(ALWAYS_AVAILABLE):
        if tool_id in seen:
            continue
        seen.add(tool_id)

        spec = TOOL_REGISTRY.get(tool_id)
        if spec is None:
            logger.warning("unknown tool id %r ignored", tool_id)
            continue
        try:
            tools.append(spec.factory(context))
        except Exception:
            logger.exception("failed to build tool %r", tool_id)

    return tools


def build_agent(spec: AgentSpec, context: ToolContext, *, verbose: bool = False) -> Agent:
    """Construct one CrewAI agent."""
    return Agent(
        role=spec.display_role,
        goal=spec.goal or "Complete the assigned task thoroughly and accurately.",
        backstory=spec.backstory or f"You are {spec.name}, a capable research agent.",
        llm=build_llm(spec.llm),
        tools=build_tools(spec.tools, context),
        verbose=verbose,
        allow_delegation=False,
        max_iter=6,
        max_retry_limit=2,
        respect_context_window=True,
    )


def build_pipeline_crew(
    specs: list[AgentSpec],
    context: ToolContext,
    *,
    max_rpm: int = 10,
    max_sources: int = 8,
    max_fetch_per_query: int = 5,
    verbose: bool = False,
) -> Crew:
    """Build the sequential four-agent research crew."""
    required = {"researcher", "web_searcher", "analyst", "summarizer"}
    provided = {spec.slug for spec in specs}
    missing = required - provided
    if missing:
        raise ConfigurationError(
            f"The research pipeline needs all four built-in agents; missing: "
            f"{', '.join(sorted(missing))}."
        )

    agents = {spec.slug: build_agent(spec, context, verbose=verbose) for spec in specs}
    tasks = build_pipeline_tasks(
        agents, max_sources=max_sources, max_fetch_per_query=max_fetch_per_query
    )

    return Crew(
        agents=list(agents.values()),
        tasks=tasks,
        process=Process.sequential,
        verbose=verbose,
        # CrewAI's own memory is disabled on purpose: semantic memory is handled
        # by our vector store so it can be scoped per user.
        memory=False,
        max_rpm=max_rpm,
    )


def build_team_crew(
    specs: list[AgentSpec],
    context: ToolContext,
    *,
    workflow: list[dict[str, Any]] | None = None,
    coordinator_slug: str | None = None,
    coordinator_instructions: str = "",
    max_rpm: int = 10,
    verbose: bool = False,
) -> Crew:
    """Build a crew from a user-composed team."""
    if not specs:
        raise ConfigurationError("A team must contain at least one agent.")

    agents = [build_agent(spec, context, verbose=verbose) for spec in specs]
    roles = {spec.slug: (spec.role or spec.name) for spec in specs}

    tasks = build_team_tasks(
        agents,
        query_placeholder="{query}",
        workflow=workflow or [],
        coordinator_role=roles.get(coordinator_slug or ""),
        coordinator_instructions=coordinator_instructions,
    )

    return Crew(
        agents=agents,
        tasks=tasks,
        process=Process.sequential,
        verbose=verbose,
        memory=False,
        max_rpm=max_rpm,
    )
