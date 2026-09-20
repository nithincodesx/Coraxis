"""Dependency container for agent tools.

Tools never import services. Everything they need — the search client, the
fetcher, memory recall, the event sink — is injected here. That keeps the
``agents`` package free of database and HTTP-layer dependencies, which is what
makes the pipeline testable without a server or a network.
"""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from coraxis.agents.citations import CitationTracker
from coraxis.agents.comms import AgentChannel
from coraxis.agents.tools.fetch import PageFetcher
from coraxis.agents.tools.search import SearchClient

#: Signature of the memory-recall function injected into the recall tool.
RecallFn = Callable[[str, str, int], Awaitable[list[dict[str, Any]]]]

#: Signature of the event sink. ``(event_type, payload)``.
EmitFn = Callable[[str, dict[str, Any]], None]

#: Called after a run should stop (cancellation or timeout).
ShouldStopFn = Callable[[], bool]


def _never_stop() -> bool:
    return False


@dataclass
class ToolContext:
    """Everything an agent tool may depend on for one run.

    One context is created per run and then specialised per agent with
    :meth:`for_agent`, so every event a tool emits is attributed to the agent
    that caused it without the tool having to know its own identity.
    """

    tracker: CitationTracker
    search: SearchClient
    fetcher: PageFetcher
    run_id: str = ""
    agent_slug: str = ""
    channel: AgentChannel = field(default_factory=AgentChannel)
    recall: RecallFn | None = None
    emit: EmitFn | None = None
    should_stop: ShouldStopFn = _never_stop

    def for_agent(self, agent_slug: str) -> ToolContext:
        """A view of this context bound to one agent.

        Shares the tracker, clients, and channel — only the attribution
        changes — so a team's agents collaborate through the same workspace.
        """
        return ToolContext(
            tracker=self.tracker,
            search=self.search,
            fetcher=self.fetcher,
            run_id=self.run_id,
            agent_slug=agent_slug,
            channel=self.channel,
            recall=self.recall,
            emit=self.emit,
            should_stop=self.should_stop,
        )

    def publish(self, event_type: str, **payload: Any) -> None:
        """Emit an event, tolerating a missing sink."""
        if self.emit is None:
            return
        payload.setdefault("agent", self.agent_slug)
        # Observability must never break a run: a failing sink is swallowed.
        with contextlib.suppress(Exception):
            self.emit(event_type, payload)

    def stopped(self) -> bool:
        """True when the run has been cancelled or has exceeded its deadline."""
        try:
            return self.should_stop()
        except Exception:  # noqa: BLE001
            return False
