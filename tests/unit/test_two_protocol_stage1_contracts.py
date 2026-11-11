"""Stage 1 contracts for the planned two-protocol Researcher boundary.

The production split is intentionally not implemented in Stage 1. Tests for
that future boundary are strict expected failures so the suite records the
missing contract without changing production behavior. Preservation tests and
the existing Groq adapter tests must pass now.
"""

from __future__ import annotations

from typing import Any

import pytest
from crewai import Agent

from coraxis.agents.citations import CitationTracker
from coraxis.agents.context import ToolContext
from coraxis.agents.crew import AgentSpec, build_pipeline_crew, build_team_crew
from coraxis.agents.tasks import SubQuestions, build_pipeline_tasks
from coraxis.agents.tools.fetch import PageFetcher
from coraxis.agents.tools.search import SearchClient
from coraxis.services.llm.factory import LLMConfig, build_llm
from coraxis.services.llm.groq_compat import GroqCompatibleLLM


def _context() -> ToolContext:
    return ToolContext(
        tracker=CitationTracker(),
        search=SearchClient(max_attempts=1),
        fetcher=PageFetcher(),
    )


def _specs(provider: str = "groq") -> list[AgentSpec]:
    return [
        AgentSpec(
            slug=slug,
            name=slug.replace("_", " ").title(),
            role=slug,
            goal=f"Complete the {slug} task.",
            backstory="Deterministic contract-test agent.",
            tools=(),
            llm=LLMConfig(
                agent_slug=slug,
                provider=provider,  # type: ignore[arg-type]
                model="openai/gpt-oss-120b" if provider == "groq" else "test-model",
                api_key="test-key" if provider != "ollama" else "",
                base_url="https://example.test/v1" if provider == "custom" else "",
            ),
        )
        for slug in ("researcher", "web_searcher", "analyst", "summarizer")
    ]


def _task_agents() -> dict[str, Agent]:
    return {
        slug: Agent(
            role=slug,
            goal=f"Act as the {slug}",
            backstory="Deterministic task-contract agent.",
            llm="ollama/llama3",
            verbose=False,
            allow_delegation=False,
        )
        for slug in ("researcher", "web_searcher", "analyst", "summarizer")
    }


def test_non_groq_builtin_pipeline_retains_existing_structured_contract() -> None:
    tasks = build_pipeline_tasks(_task_agents())

    assert len(tasks) == 4
    assert tasks[0].output_json is SubQuestions


def test_custom_team_retains_existing_sequential_team_behavior() -> None:
    specs = [
        AgentSpec(
            slug="custom-one",
            name="Custom One",
            role="Custom One",
            goal="Complete the custom task.",
            backstory="Custom team test agent.",
            tools=(),
            llm=LLMConfig(
                agent_slug="custom-one",
                provider="ollama",
                model="llama3",
            ),
        )
    ]

    crew = build_team_crew(specs, _context())

    assert len(crew.tasks) == 1
    assert crew.tasks[0].agent.role == "Custom One"
    assert crew.tasks[0].output_json is None


@pytest.mark.parametrize("provider", ["openai", "gemini", "ollama", "custom"])
def test_non_groq_providers_do_not_select_groq_adapter(provider: str) -> None:
    config = LLMConfig(
        agent_slug="researcher",
        provider=provider,  # type: ignore[arg-type]
        model="test-model" if provider != "ollama" else "llama3",
        api_key="" if provider == "ollama" else "test-key",
        base_url="https://example.test/v1" if provider == "custom" else "",
    )

    assert not isinstance(build_llm(config), GroqCompatibleLLM)


def test_builtin_groq_llm_uses_existing_instance_local_adapter() -> None:
    config = LLMConfig(
        agent_slug="researcher",
        provider="groq",
        model="openai/gpt-oss-120b",
        api_key="test-key",
    )

    assert isinstance(build_llm(config), GroqCompatibleLLM)


@pytest.mark.xfail(
    strict=True,
    reason="Stage 2 must add the built-in Groq Researcher two-protocol boundary.",
)
def test_two_protocol_boundary_is_gated_to_builtin_groq_researcher() -> None:
    """The future selector must not affect custom teams or other providers."""
    from coraxis.agents import crew as crew_module

    selector = getattr(crew_module, "build_researcher_protocols", None)
    assert selector is not None, "Stage 2 protocol selector is not implemented"

    groq = selector(agent_slug="researcher", provider="groq", builtin=True)
    non_groq = selector(agent_slug="researcher", provider="openai", builtin=True)
    custom = selector(agent_slug="researcher", provider="groq", builtin=False)

    assert groq is not None
    assert non_groq is None
    assert custom is None


@pytest.mark.xfail(
    strict=True,
    reason="Stage 2 must expose the native-tool Protocol A task boundary.",
)
def test_protocol_a_uses_native_tools_without_structured_output() -> None:
    from coraxis.agents import crew as crew_module

    builder = getattr(crew_module, "build_protocol_a_task", None)
    assert builder is not None, "Stage 2 Protocol A builder is not implemented"

    task = builder(agent=Agent(role="Researcher", goal="research", backstory="test"))

    assert task.output_json is None
    assert task.output_pydantic is None
    assert {tool.name for tool in task.agent.tools} >= {
        "web_search",
        "recall_memory",
        "send_message",
        "read_inbox",
        "blackboard_write",
        "blackboard_read",
    }


@pytest.mark.xfail(
    strict=True,
    reason="Stage 2 must expose the no-tools Protocol B formatter boundary.",
)
def test_protocol_b_uses_no_tools_and_subquestions_output_json() -> None:
    from coraxis.agents import crew as crew_module

    builder = getattr(crew_module, "build_protocol_b_formatter_task", None)
    assert builder is not None, "Stage 2 Protocol B builder is not implemented"

    task = builder(agent=Agent(role="Researcher Formatter", goal="format", backstory="test"))

    assert task.agent.tools == []
    assert task.output_json is SubQuestions


@pytest.mark.xfail(
    strict=True,
    reason="Stage 2 must wire explicit immediate-predecessor task contexts.",
)
def test_downstream_tasks_use_only_explicit_immediate_predecessor_context() -> None:
    tasks = build_pipeline_crew(_specs(), _context()).tasks

    assert tasks[1].context == [tasks[0]]
    assert tasks[2].context == [tasks[1]]
    assert tasks[3].context == [tasks[2]]


def test_existing_pipeline_contract_remains_observable_before_split() -> None:
    """Stage 1 records the current baseline that Stage 2 must replace safely."""
    tasks = build_pipeline_tasks(_task_agents())

    assert [task.agent.role for task in tasks] == [
        "researcher",
        "web_searcher",
        "analyst",
        "summarizer",
    ]
    assert all(task.output_json is not None for task in tasks)


def test_contract_fixture_payload_is_not_secret_bearing() -> None:
    """The test-only provider fixtures never contain real credentials."""
    configs: list[dict[str, Any]] = [spec.llm.describe() for spec in _specs()]

    assert all("api_key" not in config for config in configs)
