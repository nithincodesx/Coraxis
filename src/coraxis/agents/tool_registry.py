"""The catalogue of tools an agent can be granted.

Single source of truth: the API exposes this to the agent builder UI, and
:func:`coraxis.agents.crew.build_tools` resolves tool ids against it. Adding a
tool means adding one entry here and one factory function.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from coraxis.agents.context import ToolContext

if TYPE_CHECKING:
    from crewai.tools import BaseTool


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """Metadata describing one tool."""

    id: str
    label: str
    description: str
    factory: Callable[[ToolContext], BaseTool]
    requires_tracker: bool = False
    builtin_agents: tuple[str, ...] = ()


def _search_factory(context: ToolContext) -> BaseTool:
    from coraxis.agents.tools.crew_tools import SearchTool

    return SearchTool(context=context)


def _fetch_factory(context: ToolContext) -> BaseTool:
    from coraxis.agents.tools.crew_tools import FetchTool

    return FetchTool(context=context)


def _recall_factory(context: ToolContext) -> BaseTool:
    from coraxis.agents.tools.crew_tools import RecallMemoryTool

    return RecallMemoryTool(context=context)


def _register_claim_factory(context: ToolContext) -> BaseTool:
    from coraxis.agents.tools.crew_tools import RegisterClaimTool

    return RegisterClaimTool(context=context)


def _message_factory(context: ToolContext) -> BaseTool:
    from coraxis.agents.tools.crew_tools import SendMessageTool

    return SendMessageTool(context=context)


def _read_inbox_factory(context: ToolContext) -> BaseTool:
    from coraxis.agents.tools.crew_tools import ReadInboxTool

    return ReadInboxTool(context=context)


def _blackboard_write_factory(context: ToolContext) -> BaseTool:
    from coraxis.agents.tools.crew_tools import BlackboardWriteTool

    return BlackboardWriteTool(context=context)


def _blackboard_read_factory(context: ToolContext) -> BaseTool:
    from coraxis.agents.tools.crew_tools import BlackboardReadTool

    return BlackboardReadTool(context=context)


TOOL_REGISTRY: dict[str, ToolSpec] = {
    spec.id: spec
    for spec in (
        ToolSpec(
            id="web_search",
            label="Web Search",
            description="Search the web and return ranked results with titles, URLs, and snippets.",
            factory=_search_factory,
            builtin_agents=("researcher", "web_searcher"),
        ),
        ToolSpec(
            id="fetch_page",
            label="Fetch Page",
            description="Download a URL and extract its readable text, discarding navigation and boilerplate.",
            factory=_fetch_factory,
            builtin_agents=("web_searcher",),
        ),
        ToolSpec(
            id="recall_memory",
            label="Recall Memory",
            description="Search prior findings on a topic so work is not repeated.",
            factory=_recall_factory,
            builtin_agents=("researcher", "analyst"),
        ),
        ToolSpec(
            id="register_claim",
            label="Register Claim",
            description="Record a synthesised claim and its supporting sources in the citation tracker.",
            factory=_register_claim_factory,
            requires_tracker=True,
            builtin_agents=("analyst",),
        ),
        ToolSpec(
            id="send_message",
            label="Send Message",
            description="Send a message to a teammate or to every agent on the team.",
            factory=_message_factory,
            builtin_agents=("researcher", "web_searcher", "analyst", "summarizer"),
        ),
        ToolSpec(
            id="read_inbox",
            label="Read Inbox",
            description="Read messages teammates have sent.",
            factory=_read_inbox_factory,
            builtin_agents=("researcher", "web_searcher", "analyst", "summarizer"),
        ),
        ToolSpec(
            id="blackboard_write",
            label="Write to Blackboard",
            description="Publish a value to the shared workspace every agent can read.",
            factory=_blackboard_write_factory,
            builtin_agents=("researcher", "web_searcher", "analyst", "summarizer"),
        ),
        ToolSpec(
            id="blackboard_read",
            label="Read Blackboard",
            description="Read a value another agent published to the shared workspace.",
            factory=_blackboard_read_factory,
            builtin_agents=("researcher", "web_searcher", "analyst", "summarizer"),
        ),
    )
}

#: Tools every agent gets automatically, so teams can collaborate out of the box.
ALWAYS_AVAILABLE: tuple[str, ...] = (
    "send_message",
    "read_inbox",
    "blackboard_write",
    "blackboard_read",
)


def default_tools_for(agent_slug: str) -> list[str]:
    """Tool ids the built-in agent of this slug should receive."""
    return [spec.id for spec in TOOL_REGISTRY.values() if agent_slug in spec.builtin_agents]


def validate_tool_ids(tool_ids: list[str]) -> list[str]:
    """Return the unknown ids in a requested tool list."""
    return [tool_id for tool_id in tool_ids if tool_id not in TOOL_REGISTRY]
