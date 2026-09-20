"""Tool construction and context wiring.

Regression guard for a subtle failure mode. CrewAI's `BaseTool` is a pydantic
model, and `ToolContext` is a dataclass, so declaring the context as a plain
field is only safe if pydantic hands back the *same object*. If it ever starts
copying or reconstructing it, every tool silently gets its own context: events
would be published to a copy, and a run would appear to produce no activity at
all while still returning a report. Nothing else in the suite would catch that.

The other half of the same problem: pydantic's mypy plugin synthesises
`__init__` from the model's fields and discards an explicitly defined one, so a
positional `context` argument works at runtime but fails type checking. These
tests pin the keyword form the registry now uses.
"""

from __future__ import annotations

import asyncio

import pytest

from coraxis.agents.citations import CitationTracker
from coraxis.agents.context import ToolContext
from coraxis.agents.tool_registry import TOOL_REGISTRY
from coraxis.agents.tools.crew_tools import ContextTool, SearchTool


def _context(agent_slug: str = "researcher") -> ToolContext:
    """A context with only what tool construction needs."""
    return ToolContext(
        tracker=CitationTracker(),
        search=None,  # type: ignore[arg-type]
        fetcher=None,  # type: ignore[arg-type]
        run_id="run-1",
        agent_slug=agent_slug,
    )


def test_context_is_stored_by_reference_not_copied() -> None:
    """The tool must hold the very context it was given."""
    context = _context()
    tool = SearchTool(context=context)

    assert tool.context is context
    assert tool.context.run_id == "run-1"
    assert tool.context.agent_slug == "researcher"


def test_every_registered_tool_shares_one_context() -> None:
    """A run's tools all report into the same tracker and the same run."""
    context = _context()
    tools = [spec.factory(context) for spec in TOOL_REGISTRY.values()]

    assert len(tools) == len(TOOL_REGISTRY)
    assert all(tool.context is context for tool in tools)

    # Prove the sharing is real, not just referential: a mutation through one
    # tool is visible from the context the run holds.
    tools[0].context.tracker.add_source("https://example.com", relevance=0.9)
    assert len(context.tracker) == 1


def test_the_context_never_leaks_into_serialisation() -> None:
    """`model_dump` feeds tool schemas sent to the model; the context must not."""
    tool = SearchTool(context=_context())

    dumped = tool.model_dump()
    assert "context" not in dumped
    assert "ToolContext" not in repr(tool)
    assert "ToolContext" not in str(dumped)


def test_tools_are_constructible_for_every_registered_spec() -> None:
    """Each factory returns a usable tool with a name and description."""
    context = _context()
    for spec in TOOL_REGISTRY.values():
        tool = spec.factory(context)
        assert isinstance(tool, ContextTool)
        assert tool.name
        assert tool.description
        assert tool.args_schema is not None


async def test_async_tools_are_awaitable_and_the_sync_bridge_refuses_a_live_loop() -> None:
    """The sync bridge must fail loudly rather than call `asyncio.run` in a loop.

    `asyncio.run` raises a bare RuntimeError when a loop is already running,
    which is the failure the previous implementation produced. The bridge is
    supposed to explain the fix instead.
    """
    context = _context()
    tool = TOOL_REGISTRY["recall_memory"].factory(context)

    with pytest.raises(RuntimeError) as excinfo:
        tool._run(topic="anything", query="anything")

    assert "kickoff_async" in str(excinfo.value)


def test_the_sync_bridge_works_when_there_is_no_loop() -> None:
    """With no loop running, the bridge is allowed to drive the coroutine."""

    class Echo(ContextTool):
        name: str = "echo"
        description: str = "Echo the value back."

        async def _arun(self, value: str = "") -> str:  # type: ignore[override]
            return f"echo:{value}"

    tool = Echo(context=_context())
    assert tool._run(value="hi") == "echo:hi"


def test_a_running_loop_does_not_break_awaiting_the_async_path() -> None:
    """The async path is the real one; make sure it still works under a loop."""

    class Echo(ContextTool):
        name: str = "echo"
        description: str = "Echo the value back."

        async def _arun(self, value: str = "") -> str:  # type: ignore[override]
            return f"echo:{value}"

    async def main() -> str:
        return await Echo(context=_context())._arun(value="async")

    assert asyncio.run(main()) == "echo:async"
