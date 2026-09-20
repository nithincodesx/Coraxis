"""CrewAI tool implementations.

Each tool's real work lives in ``_arun``. ``_run`` exists only because
CrewAI's ``BaseTool`` declares it abstract; it bridges to the async
implementation when — and only when — there is no running event loop in the
calling thread, and otherwise fails loudly with an explanation.

That is a deliberate, documented bridge. The previous implementation called
``asyncio.run`` unconditionally from library code, which raises a bare
``RuntimeError`` the moment anything invokes it from async context.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from crewai.tools import BaseTool
from pydantic import BaseModel, ConfigDict, Field

from coraxis.agents.context import ToolContext

_SYNC_BRIDGE_HINT = (
    "This tool must be awaited. Drive the crew with `kickoff_async()` rather "
    "than `kickoff()`, or the async tool implementation cannot be reached."
)


class ContextTool(BaseTool):
    """Base class carrying the injected :class:`ToolContext`.

    The context is a declared field rather than a ``PrivateAttr`` handed in
    through ``__init__``. That is not a style preference: CrewAI's ``BaseTool``
    is a pydantic model, and the pydantic mypy plugin synthesises ``__init__``
    from the model's fields — discarding an explicitly defined one. A positional
    ``context`` argument therefore works at runtime but type-checks as an error,
    and every construction site needed a suppression. Declaring the field makes
    the runtime and the type checker agree, with no ignores.

    ``exclude=True`` keeps it out of ``model_dump()``, so the context — which
    holds a citation tracker and a lock — is never serialised.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    context: ToolContext = Field(exclude=True, repr=False)

    async def _arun(self, *args: Any, **kwargs: Any) -> str:
        """Async entry point. Subclasses replace this with the real work.

        Declared here so the synchronous bridge below has a known return type;
        without it ``self._arun`` is an attribute mypy cannot resolve and the
        bridge degrades to ``Any``.
        """
        raise NotImplementedError

    def _run(self, *args: Any, **kwargs: Any) -> str:  # type: ignore[override]
        """Synchronous entry point. See the module docstring."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No loop here: running one for the duration of this call is safe.
            return asyncio.run(self._arun(*args, **kwargs))
        raise RuntimeError(_SYNC_BRIDGE_HINT)

    @staticmethod
    def _dumps(payload: Any) -> str:
        return json.dumps(payload, ensure_ascii=False, default=str)


# ─── Input schemas ───────────────────────────────────────────────────


class SearchInput(BaseModel):
    query: str = Field(..., description="The search query. Be specific.")
    max_results: int = Field(default=8, ge=1, le=20, description="How many results to return.")


class FetchInput(BaseModel):
    url: str = Field(..., description="The absolute URL to fetch.")


class RecallInput(BaseModel):
    topic: str = Field(..., description="The research topic the memory is filed under.")
    query: str = Field(..., description="What you want to recall about that topic.")
    n_results: int = Field(default=5, ge=1, le=20, description="How many prior findings to return.")


class RegisterClaimInput(BaseModel):
    claim_text: str = Field(..., description="The claim, stated as a single factual sentence.")
    source_urls: list[str] = Field(..., description="URLs that support this claim.")
    confidence: float = Field(
        default=0.7, ge=0.0, le=1.0, description="Calibrated confidence, 0-1."
    )
    relevance_scores: list[float] | None = Field(
        default=None, description="Relevance per source, 0-1, in the same order as source_urls."
    )
    agent: str = Field(default="analyst", description="Name of the agent registering the claim.")


class SendMessageInput(BaseModel):
    to_agent: str = Field(..., description="Recipient agent name, or 'all' to broadcast.")
    message: str = Field(..., description="The message body.")


class ReadInboxInput(BaseModel):
    limit: int = Field(default=10, ge=1, le=50, description="How many recent messages to read.")


class BlackboardWriteInput(BaseModel):
    key: str = Field(..., description="The key to publish under.")
    value: str = Field(
        ..., description="The value to store. Use a JSON string for structured data."
    )


class BlackboardReadInput(BaseModel):
    key: str = Field(..., description="The key to read.")


# ─── Tools ───────────────────────────────────────────────────────────


class SearchTool(ContextTool):
    name: str = "web_search"
    description: str = (
        "Search the web for a query. Returns ranked results with title, URL, and snippet. "
        "Every result is registered as a citation so it can be referenced later."
    )
    args_schema: type[BaseModel] = SearchInput

    async def _arun(self, query: str, max_results: int = 8) -> str:  # type: ignore[override]
        if self.context.stopped():
            return self._dumps({"error": "Run cancelled.", "results": []})

        self.context.publish("tool.started", tool=self.name, detail=query[:160])
        results = await self.context.search.search(query, max_results)

        for result in results:
            self.context.tracker.add_source(
                result.url,
                title=result.title,
                relevance=0.5,  # provisional; the analyst re-scores
                snippet=result.snippet,
            )

        self.context.publish(
            "tool.completed", tool=self.name, detail=f"{len(results)} results", count=len(results)
        )
        return self._dumps({"query": query, "results": [r.to_dict() for r in results]})


class FetchTool(ContextTool):
    name: str = "fetch_page"
    description: str = (
        "Download a URL and extract its readable text. Returns the title, the full text, "
        "and the word count. Content that is too short or behind a paywall is reported as a failure."
    )
    args_schema: type[BaseModel] = FetchInput

    async def _arun(self, url: str) -> str:  # type: ignore[override]
        if self.context.stopped():
            return self._dumps({"error": "Run cancelled."})

        self.context.publish("tool.started", tool=self.name, detail=url[:160])
        page = await self.context.fetcher.fetch(url)

        if page.success:
            self.context.tracker.add_source(
                url,
                title=page.title,
                relevance=0.6,
                word_count=page.word_count,
                fetch_success=True,
            )
            self.context.publish(
                "tool.completed", tool=self.name, detail=f"{page.word_count} words"
            )
        else:
            self.context.publish("tool.completed", tool=self.name, detail=page.error[:120])

        # Truncated deliberately: dumping 40k characters into the prompt crowds
        # out the agent's actual reasoning.
        return self._dumps(
            {
                "url": page.url,
                "title": page.title,
                "text": page.text[:12000],
                "word_count": page.word_count,
                "truncated": len(page.text) > 12000,
                "success": page.success,
                "error": page.error,
            }
        )


class RecallMemoryTool(ContextTool):
    name: str = "recall_memory"
    description: str = (
        "Search findings from previous research runs on a topic. "
        "Use this before searching the web, so you do not repeat work already done."
    )
    args_schema: type[BaseModel] = RecallInput

    async def _arun(self, topic: str, query: str, n_results: int = 5) -> str:  # type: ignore[override]
        if self.context.recall is None:
            return self._dumps(
                {"topic": topic, "results": [], "note": "Semantic memory is disabled."}
            )

        try:
            entries = await self.context.recall(topic, query, n_results)
        except Exception as exc:  # noqa: BLE001 - memory is an optimisation, not a requirement
            self.context.publish(
                "tool.completed", tool=self.name, detail=f"recall failed: {exc}"[:120]
            )
            return self._dumps({"topic": topic, "results": [], "error": str(exc)[:200]})

        self.context.publish(
            "tool.completed", tool=self.name, detail=f"{len(entries)} prior findings"
        )
        return self._dumps({"topic": topic, "results": entries})


class RegisterClaimTool(ContextTool):
    name: str = "register_claim"
    description: str = (
        "Record a synthesised claim together with the sources that support it. "
        "Call this for every claim you want to appear with a citation in the final report."
    )
    args_schema: type[BaseModel] = RegisterClaimInput

    async def _arun(  # type: ignore[override]
        self,
        claim_text: str,
        source_urls: list[str],
        confidence: float = 0.7,
        relevance_scores: list[float] | None = None,
        agent: str = "analyst",
    ) -> str:
        claim_ref = self.context.tracker.add_claim(
            claim_text,
            source_urls,
            confidence=confidence,
            agent=agent,
            relevance_scores=relevance_scores,
        )
        if not claim_ref:
            return self._dumps({"error": "Claim text was empty; nothing registered."})

        self.context.publish(
            "claim.registered",
            claim_ref=claim_ref,
            confidence=confidence,
            detail=claim_text[:160],
        )
        return self._dumps({"claim_ref": claim_ref, "sources": len(source_urls)})


class SendMessageTool(ContextTool):
    name: str = "send_message"
    description: str = (
        "Send a message to a teammate, or to 'all' to broadcast. "
        "Use this to hand off findings, ask for help, or flag a problem."
    )
    args_schema: type[BaseModel] = SendMessageInput

    async def _arun(self, to_agent: str, message: str) -> str:  # type: ignore[override]
        sent = self.context.channel.send(self.name, to_agent, message)
        self.context.publish(
            "agent.message",
            to_agent=to_agent,
            detail=message[:200],
        )
        return self._dumps(sent.to_dict())


class ReadInboxTool(ContextTool):
    name: str = "read_inbox"
    description: str = "Read recent messages teammates have sent you."
    args_schema: type[BaseModel] = ReadInboxInput

    async def _arun(self, limit: int = 10) -> str:  # type: ignore[override]
        agent = getattr(self, "_agent_name", "") or "unknown"
        messages = self.context.channel.inbox(agent, limit)
        return self._dumps({"messages": [message.to_dict() for message in messages]})


class BlackboardWriteTool(ContextTool):
    name: str = "blackboard_write"
    description: str = (
        "Publish a value to the shared workspace. Every agent on the team can read it. "
        "Use this to share intermediate results without messaging each agent individually."
    )
    args_schema: type[BaseModel] = BlackboardWriteInput

    async def _arun(self, key: str, value: str) -> str:  # type: ignore[override]
        self.context.channel.post(key, value, agent=self.name)
        self.context.publish("blackboard.write", key=key, detail=str(value)[:160])
        return self._dumps({"key": key, "stored": True})


class BlackboardReadTool(ContextTool):
    name: str = "blackboard_read"
    description: str = "Read a value another agent published to the shared workspace."
    args_schema: type[BaseModel] = BlackboardReadInput

    async def _arun(self, key: str) -> str:  # type: ignore[override]
        value = self.context.channel.read(key)
        if value is None:
            return self._dumps({"key": key, "found": False})
        return self._dumps({"key": key, "found": True, "value": value})
