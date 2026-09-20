"""Run execution.

This module owns the lifecycle of a research run: resolve configuration, drive
the crew, persist everything, and guarantee a terminal state is written exactly
once. It replaces a global ``GlobalState`` singleton and an unmanaged daemon
thread with something that can be cancelled, timed out, and reasoned about.

Two invariants hold throughout:

* every event is persisted with a monotonic ``seq`` before it is broadcast, so
  a reconnecting client can resume from a cursor and never sees a gap;
* the run reaches a terminal status on every path, including cancellation and
  timeout, so a run can never get stuck occupying a user's concurrency quota.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass
from typing import Any

from coraxis.agents.citations import CitationTracker
from coraxis.agents.context import ToolContext
from coraxis.agents.crew import AgentSpec, build_pipeline_crew, build_team_crew
from coraxis.agents.tasks import FinalReport, ReportStats
from coraxis.agents.tools.fetch import PageFetcher
from coraxis.agents.tools.search import SearchClient
from coraxis.core.config import Settings, get_settings
from coraxis.core.errors import ConfigurationError, CoraxisError
from coraxis.core.logging import get_logger, run_id_var
from coraxis.db.enums import EventLevel, EventType, RunStatus
from coraxis.db.session import session_scope
from coraxis.repositories import agents as agent_repo
from coraxis.repositories import credentials as credential_repo
from coraxis.repositories import memory as memory_repo
from coraxis.repositories import runs as run_repo
from coraxis.repositories import teams as team_repo
from coraxis.services.events import RunEventBus, event_bus
from coraxis.services.llm.factory import LLMConfig
from coraxis.services.vectorstore import VectorStore

logger = get_logger("research")

#: Event persistence is batched: flush when the batch fills, or when the queue
#: has been idle this long. One transaction per batch, not per event.
_BATCH_SIZE = 64
_FLUSH_INTERVAL_SECONDS = 0.25

#: How often the worker re-reads the cancellation flag from the database.
_CANCEL_POLL_SECONDS = 2.0

_STOP = object()


# ─────────────────────────────────────────────────────────────────────
#  Event recording
# ─────────────────────────────────────────────────────────────────────


class EventRecorder:
    """Bridges synchronous tool callbacks to persisted, broadcast events.

    ``emit`` is safe to call from any thread — including the CrewAI worker
    thread — because it hops onto the serving event loop before touching the
    queue. A background task drains the queue in batches, assigns sequence
    numbers, commits, and only then broadcasts.
    """

    def __init__(self, run_id: str, loop: asyncio.AbstractEventLoop, bus: RunEventBus) -> None:
        self.run_id = run_id
        self._loop = loop
        self._bus = bus
        self._queue: asyncio.Queue[Any] = asyncio.Queue()
        self._task: asyncio.Task[None] | None = None

    def emit(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        """Queue an event. Never blocks, never raises."""
        # The loop may be shutting down; losing a progress event is acceptable.
        with contextlib.suppress(RuntimeError):
            self._loop.call_soon_threadsafe(
                self._queue.put_nowait, (event_type, dict(payload or {}))
            )

    def start(self) -> None:
        self._task = asyncio.create_task(self._drain(), name=f"events:{self.run_id}")

    async def stop(self) -> None:
        """Flush and stop. Safe to call more than once."""
        if self._task is None:
            return
        try:
            self._loop.call_soon_threadsafe(self._queue.put_nowait, _STOP)
            await asyncio.wait_for(self._task, timeout=10.0)
        except (TimeoutError, asyncio.CancelledError):  # pragma: no cover - shutdown race
            self._task.cancel()
        finally:
            self._task = None

    async def _drain(self) -> None:
        pending: list[tuple[str, dict[str, Any]]] = []

        while True:
            try:
                item = await asyncio.wait_for(self._queue.get(), _FLUSH_INTERVAL_SECONDS)
            except TimeoutError:
                await self._flush(pending)
                pending = []
                continue

            if item is _STOP:
                await self._flush(pending)
                return

            pending.append(item)
            if len(pending) >= _BATCH_SIZE:
                await self._flush(pending)
                pending = []

    async def _flush(self, batch: list[tuple[str, dict[str, Any]]]) -> None:
        if not batch:
            return

        broadcast: list[dict[str, Any]] = []
        try:
            async with session_scope() as session:
                for event_type, payload in batch:
                    payload = dict(payload)
                    message = str(payload.pop("detail", "") or payload.pop("message", "") or "")
                    level = str(
                        payload.pop("level", EventLevel.INFO.value) or EventLevel.INFO.value
                    )
                    agent = str(payload.pop("agent", "") or "")

                    event = await run_repo.add_event(
                        session,
                        self.run_id,
                        type=_coerce_event_type(event_type),
                        agent=agent,
                        level=_coerce_level(level),
                        message=message,
                        payload=payload,
                    )
                    broadcast.append(
                        {
                            "id": event.id,
                            "seq": event.seq,
                            "type": event.type,
                            "agent": event.agent,
                            "level": event.level,
                            "message": event.message,
                            "payload": event.payload,
                            "created_at": event.created_at.isoformat() + "Z",
                        }
                    )
        except Exception:
            # Persistence failed. Do not broadcast unpersisted events: a client
            # resuming from a cursor would then see a gap.
            logger.exception("failed to persist %d events for run %s", len(batch), self.run_id)
            return

        # Named separately from the loop above, where `event` is an ORM row.
        for broadcast_event in broadcast:
            self._bus.publish(self.run_id, broadcast_event)


def _coerce_event_type(value: str) -> EventType:
    try:
        return EventType(value)
    except ValueError:
        return EventType.LOG


def _coerce_level(value: str) -> EventLevel:
    try:
        return EventLevel(value)
    except ValueError:
        return EventLevel.INFO


# ─────────────────────────────────────────────────────────────────────
#  Cancellation and deadline
# ─────────────────────────────────────────────────────────────────────


class StopSignal:
    """Cooperative stop flag shared with the agent tools.

    ``should_stop`` is polled by tools between steps; ``cancelled`` is set by a
    watcher task that re-reads the database, so a Cancel click takes effect
    within a couple of seconds without the worker holding a long transaction.
    """

    def __init__(self, timeout_seconds: int) -> None:
        self._deadline = time.monotonic() + timeout_seconds
        self._cancelled = False

    def mark_cancelled(self) -> None:
        self._cancelled = True

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    @property
    def timed_out(self) -> bool:
        return time.monotonic() > self._deadline

    def __call__(self) -> bool:
        return self._cancelled or self.timed_out


async def _watch_for_cancellation(run_id: str, signal: StopSignal) -> None:
    """Poll the database for a cancel request until the signal fires."""
    while not signal():
        await asyncio.sleep(_CANCEL_POLL_SECONDS)
        try:
            async with session_scope() as session:
                if await run_repo.is_cancel_requested(session, run_id):
                    logger.info("cancellation requested for run %s", run_id)
                    signal.mark_cancelled()
                    return
        except Exception:
            logger.warning("cancellation poll failed for run %s", run_id, exc_info=True)


# ─────────────────────────────────────────────────────────────────────
#  Orchestrator
# ─────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _RunPlan:
    """Everything needed to execute a run, resolved up front."""

    user_id: str
    query: str
    options: dict[str, Any]
    specs: list[AgentSpec]
    workflow: list[dict[str, Any]]
    coordinator_slug: str | None
    coordinator_instructions: str
    is_team: bool


class ResearchOrchestrator:
    """Executes a single research run end to end."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        bus: RunEventBus | None = None,
        vector_store: VectorStore | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.bus = bus or event_bus
        self._vector_store = vector_store

    @property
    def vector_store(self) -> VectorStore:
        if self._vector_store is None:
            self._vector_store = VectorStore(
                path=self.settings.chroma_path, model_name=self.settings.embedding_model
            )
        return self._vector_store

    # ── Entry point ──────────────────────────────────────────────────

    async def execute(self, run_id: str) -> None:
        """Run a previously created run record to completion.

        Always leaves the run in a terminal state.
        """
        token = run_id_var.set(run_id)
        try:
            plan = await self._prepare(run_id)
            if plan is None:
                return  # already terminal, or gone
            await self._drive(run_id, plan)
        except asyncio.CancelledError:
            await self._finalise(run_id, RunStatus.CANCELLED, "Run was cancelled.")
            raise
        except Exception as exc:
            logger.exception("run %s failed", run_id)
            await self._finalise(run_id, RunStatus.FAILED, _describe(exc))
        finally:
            run_id_var.reset(token)

    # ── Preparation ──────────────────────────────────────────────────

    async def _prepare(self, run_id: str) -> _RunPlan | None:
        """Load the run, resolve its agents, and mark it started."""
        async with session_scope() as session:
            run = await run_repo.get_run_unscoped(session, run_id)
            if run is None:
                logger.warning("run %s no longer exists", run_id)
                return None
            if run.is_terminal:
                logger.info("run %s is already %s; nothing to do", run_id, run.status)
                return None

            await run_repo.mark_started(session, run)
            user_id = run.user_id
            query = run.query
            options = dict(run.options or {})
            team_id = run.team_id

            specs, workflow, coordinator, instructions = await self._resolve_specs(
                session, user_id, team_id
            )

        return _RunPlan(
            user_id=user_id,
            query=query,
            options=options,
            specs=specs,
            workflow=workflow,
            coordinator_slug=coordinator,
            coordinator_instructions=instructions,
            is_team=team_id is not None,
        )

    async def _resolve_specs(
        self, session: Any, user_id: str, team_id: str | None
    ) -> tuple[list[AgentSpec], list[dict[str, Any]], str | None, str]:
        """Turn stored definitions plus per-user settings into runnable specs."""
        definitions = await agent_repo.list_definitions(session, user_id)
        llm_settings = await agent_repo.list_llm_settings(session, user_id)
        stored_credentials = await credential_repo.list_for_user(session, user_id)
        by_provider = {credential.provider: credential for credential in stored_credentials}

        # An agent with no provider of its own should use whatever the user
        # actually configured, rather than a hardcoded guess. Otherwise adding
        # only a custom key leaves every default agent pointed at Groq with no
        # key, which reads as "my key doesn't work".
        fallback_provider = next(
            (
                provider
                for provider in ("custom", "groq", "openai", "gemini", "ollama")
                if by_provider.get(provider) is not None
                and (by_provider[provider].encrypted_key or provider == "ollama")
            ),
            "groq",
        )

        def make_spec(definition: Any) -> AgentSpec:
            return AgentSpec(
                slug=definition.slug,
                name=definition.name,
                role=definition.role,
                goal=definition.goal,
                backstory=definition.backstory,
                tools=tuple(definition.tools or []),
                llm=self._llm_config(
                    definition.slug,
                    llm_settings.get(definition.slug),
                    by_provider,
                    fallback_provider,
                ),
            )

        by_slug = {definition.slug: definition for definition in definitions}

        if team_id is None:
            missing = [
                slug
                for slug in ("researcher", "web_searcher", "analyst", "summarizer")
                if slug not in by_slug
            ]
            if missing:
                raise ConfigurationError(
                    "Built-in agents are missing from the database. Run "
                    "`alembic upgrade head` to seed them."
                )
            specs = [
                make_spec(by_slug[slug])
                for slug in ("researcher", "web_searcher", "analyst", "summarizer")
            ]
            return specs, [], None, ""

        team = await team_repo.get_team(session, user_id, team_id)
        if team is None:
            raise ConfigurationError("The team for this run no longer exists.")

        specs = []
        for member in team.members:
            definition = by_slug.get(member.agent_slug)
            if definition is None:
                logger.warning(
                    "team %s references unknown agent %r; skipping", team.id, member.agent_slug
                )
                continue
            specs.append(make_spec(definition))

        if not specs:
            raise ConfigurationError("This team has no resolvable agents.")

        workflow = [
            {
                "agent_name": step.agent_slug,
                "description": step.description,
                "expected_output": step.expected_output,
            }
            for step in team.steps
        ]
        return specs, workflow, team.coordinator_slug, team.coordinator_instructions

    def _llm_config(
        self,
        agent_slug: str,
        settings_row: Any,
        credentials_by_provider: dict[str, Any],
        fallback_provider: str = "groq",
    ) -> LLMConfig:
        """Resolve one agent's provider, model, and key.

        The model resolves through three levels, most specific first: the
        agent's own setting, then the model the user pinned for that provider in
        Settings, then the built-in default. Without the middle level, pinning a
        model in Settings would silently do nothing for every agent that had
        never been given an explicit model.
        """
        provider = (settings_row.provider if settings_row else "") or fallback_provider
        credential = credentials_by_provider.get(provider)

        model = (settings_row.model if settings_row else "") or ""
        if not model and credential is not None:
            model = credential.default_model or ""

        temperature = float(settings_row.temperature) if settings_row else 0.2
        max_tokens = int(settings_row.max_tokens) if settings_row else 4096

        # A custom OpenAI-compatible endpoint keeps its base URL on the
        # credential, so an agent with no explicit URL still resolves.
        base_url = (settings_row.base_url if settings_row else "") or ""
        if not base_url and credential is not None:
            base_url = credential.base_url or ""

        api_key, source = credential_repo.resolve_api_key(credential, provider)

        return LLMConfig(
            agent_slug=agent_slug,
            provider=provider,  # type: ignore[arg-type]
            model=model,
            api_key=api_key,
            base_url=base_url,
            temperature=temperature,
            max_tokens=max_tokens,
            key_source=source,
        )

    # ── Execution ────────────────────────────────────────────────────

    async def _drive(self, run_id: str, plan: _RunPlan) -> None:
        loop = asyncio.get_running_loop()
        recorder = EventRecorder(run_id, loop, self.bus)
        recorder.start()

        signal = StopSignal(self.settings.run_timeout_seconds)
        watcher = asyncio.create_task(
            _watch_for_cancellation(run_id, signal), name=f"cancel-watch:{run_id}"
        )

        tracker = CitationTracker()
        fetcher = PageFetcher(
            timeout=float(self.settings.http_timeout_seconds),
            min_word_count=self.settings.min_word_count,
        )

        context = ToolContext(
            tracker=tracker,
            search=SearchClient(
                max_results=int(plan.options.get("max_sources") or self.settings.max_sources)
            ),
            fetcher=fetcher,
            run_id=run_id,
            recall=self._make_recall(plan.user_id),
            emit=recorder.emit,
            should_stop=signal,
        )

        await self._emit(recorder, EventType.RUN_STARTED, f"Research started: {plan.query[:200]}")

        try:
            crew = self._build_crew(plan, context)
            result = await asyncio.wait_for(
                crew.kickoff_async(inputs={"query": plan.query}),
                timeout=self.settings.run_timeout_seconds,
            )
        except TimeoutError:
            await self._finalise(
                run_id, RunStatus.TIMED_OUT, _timeout_message(self.settings.run_timeout_seconds)
            )
            return
        finally:
            watcher.cancel()
            await fetcher.aclose()
            await recorder.stop()

        if signal.cancelled:
            await self._finalise(run_id, RunStatus.CANCELLED, "Run was cancelled.")
            return

        report = _parse_report(result)
        await self._persist_result(run_id, plan, report, tracker)
        await self._emit(
            recorder,
            EventType.RUN_SUCCEEDED,
            "Research complete.",
            level=EventLevel.SUCCESS.value,
        )

    def _build_crew(self, plan: _RunPlan, context: ToolContext) -> Any:
        options = plan.options
        if plan.is_team:
            return build_team_crew(
                plan.specs,
                context,
                workflow=plan.workflow,
                coordinator_slug=plan.coordinator_slug,
                coordinator_instructions=plan.coordinator_instructions,
                max_rpm=self.settings.crew_max_rpm,
                verbose=self.settings.debug,
            )
        return build_pipeline_crew(
            plan.specs,
            context,
            max_rpm=self.settings.crew_max_rpm,
            max_sources=int(options.get("max_sources") or self.settings.max_sources),
            max_fetch_per_query=int(
                options.get("max_fetch_per_query") or self.settings.max_fetch_per_query
            ),
            verbose=self.settings.debug,
        )

    def _make_recall(self, user_id: str):
        """Build the memory-recall callable injected into the recall tool."""
        if not self.settings.memory_enabled:
            return None

        store = self.vector_store

        async def recall(topic: str, query: str, n_results: int = 5) -> list[dict[str, Any]]:
            return await store.query(user_id, topic, query, n_results=n_results)

        return recall

    # ── Persistence ──────────────────────────────────────────────────

    async def _persist_result(
        self,
        run_id: str,
        plan: _RunPlan,
        report: FinalReport,
        tracker: CitationTracker,
    ) -> None:
        """Write the report, its evidence, and its memory entries."""
        stats = tracker.stats()
        stats["agents_used"] = [spec.slug for spec in plan.specs]
        stats["models_used"] = {
            spec.slug: f"{spec.llm.provider}/{spec.llm.model or 'default'}" for spec in plan.specs
        }

        async with session_scope() as session:
            run = await run_repo.get_run_unscoped(session, run_id)
            if run is None:
                return

            await run_repo.replace_sources(session, run_id, tracker.source_payload())
            await run_repo.replace_claims(session, run_id, tracker.claim_payload())
            await run_repo.attach_report(
                session,
                run,
                report_markdown=report.markdown,
                executive_summary=report.executive_summary,
                key_findings=report.key_findings,
                citations_markdown=report.citations_markdown or tracker.format_markdown(),
                stats=stats,
            )
            await run_repo.mark_finished(session, run, status=RunStatus.SUCCEEDED)

        if plan.options.get("include_memory", True) and self.settings.memory_enabled:
            await self._write_memory(plan.user_id, run_id, plan.query, tracker)

        logger.info(
            "run %s succeeded: %d sources, %d claims",
            run_id,
            stats.get("total_sources", 0),
            stats.get("total_claims", 0),
        )

    async def _write_memory(
        self, user_id: str, run_id: str, topic: str, tracker: CitationTracker
    ) -> None:
        """Mirror findings into the vector store and the relational table."""
        entries = [
            {
                "topic": topic,
                "claim": claim["text"],
                "sources": claim.get("source_urls", []),
                "confidence": claim.get("confidence", 0.0),
                "relevance": claim.get("relevance", 0.0),
                "agent": claim.get("agent", "analyst"),
            }
            for claim in tracker.claim_payload()
        ]
        if not entries:
            return

        vector_ids = await self.vector_store.upsert(user_id, topic, entries)
        for entry, vector_id in zip(entries, vector_ids, strict=False):
            entry["vector_id"] = vector_id

        async with session_scope() as session:
            await memory_repo.create_records(session, user_id, run_id=run_id, entries=entries)

    async def _finalise(self, run_id: str, status: RunStatus, error: str) -> None:
        """Write a terminal status and broadcast it."""
        try:
            async with session_scope() as session:
                run = await run_repo.get_run_unscoped(session, run_id)
                if run is None or run.is_terminal:
                    return
                await run_repo.mark_finished(session, run, status=status, error=error)
                event = await run_repo.add_event(
                    session,
                    run_id,
                    type={
                        RunStatus.CANCELLED: EventType.RUN_CANCELLED,
                        RunStatus.TIMED_OUT: EventType.RUN_TIMED_OUT,
                        RunStatus.SUCCEEDED: EventType.RUN_SUCCEEDED,
                    }.get(status, EventType.RUN_FAILED),
                    # Enum members, not their ``.value``: the repository does
                    # ``level.value`` internally. Passing the raw string made
                    # this raise AttributeError, and because it is the last
                    # write of a failed run, the run stayed 'running' forever
                    # and its terminal event was never recorded.
                    level=EventLevel.ERROR if status is RunStatus.FAILED else EventLevel.WARNING,
                    message=error[:2000],
                )
                payload = {
                    "id": event.id,
                    "seq": event.seq,
                    "type": event.type,
                    "agent": "",
                    "level": event.level,
                    "message": event.message,
                    "payload": {},
                    "created_at": event.created_at.isoformat() + "Z",
                }
        except Exception:
            logger.exception("failed to finalise run %s", run_id)
            return

        self.bus.publish(run_id, payload)

    @staticmethod
    async def _emit(
        recorder: EventRecorder,
        event_type: EventType,
        message: str,
        *,
        level: str = EventLevel.INFO.value,
        **extra: Any,
    ) -> None:
        recorder.emit(event_type.value, {"detail": message, "level": level, **extra})
        # Give the drain task a moment so terminal events land before the caller
        # returns and the recorder is stopped.
        await asyncio.sleep(0)


# ─────────────────────────────────────────────────────────────────────
#  Result parsing
# ─────────────────────────────────────────────────────────────────────


def _parse_report(result: Any) -> FinalReport:
    """Coerce a CrewAI result into a :class:`FinalReport`.

    A model that ignores its output schema should still produce a usable
    report, so the fallback wraps the raw text rather than raising.
    """
    candidate = getattr(result, "pydantic", None)
    if isinstance(candidate, FinalReport):
        return candidate
    if candidate is not None and hasattr(candidate, "model_dump"):
        try:
            return FinalReport.model_validate(candidate.model_dump())
        except Exception:  # noqa: BLE001 - fall through to raw parsing
            pass

    raw = getattr(result, "raw", None) or str(result)

    try:
        return FinalReport.model_validate_json(raw)
    except Exception:  # noqa: BLE001 - not JSON, treat as markdown
        pass

    try:
        import json

        payload = json.loads(raw)
        if isinstance(payload, dict):
            return FinalReport.model_validate(payload)
    except Exception:  # noqa: BLE001
        pass

    return FinalReport(
        markdown=raw,
        executive_summary="",
        key_findings=[],
        citations_markdown="",
        stats=ReportStats(),
    )


def _describe(exc: BaseException) -> str:
    if isinstance(exc, CoraxisError):
        return exc.detail
    return f"{type(exc).__name__}: {exc}"[:2000]


def _timeout_message(seconds: int) -> str:
    minutes = seconds // 60
    return (
        f"Run exceeded its {minutes}-minute limit and was stopped. "
        "Try a narrower query, or raise CORAXIS_RUN_TIMEOUT_SECONDS."
    )
