"""Reproducible evaluation harness for the research pipeline.

The harness drives benchmark cases through the pipeline, captures every
intermediate output, computes automatic metrics, and stores a deterministic
record that can be compared across Phase 02 subphases.

Two modes are supported:

* :meth:`run_case` — executes the real pipeline against a benchmark question.
  Requires a working LLM provider and network access. If neither is available
  (the current development environment), it raises :class:`BaselineBlocked`
  with a clear message rather than fabricating output.
* :meth:`load_case` — loads a previously captured case record from disk. Used
  to restore the original baseline for comparison without re-executing.

All captured records are JSON-serializable and stored under the evaluation
baseline directory. Nothing here is imported by the API or by production
execution code.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from coraxis.agents.citations import CitationTracker
from coraxis.agents.context import ToolContext
from coraxis.agents.crew import AgentSpec, build_pipeline_crew
from coraxis.agents.tasks import FinalReport, ReportStats
from coraxis.agents.tools.fetch import PageFetcher
from coraxis.agents.tools.search import SearchClient
from coraxis.core.config import get_settings
from coraxis.core.logging import run_id_var
from coraxis.services.llm.factory import LLMConfig

from .benchmark import BenchmarkQuestion
from .metrics import compute_metrics

#: Environment variables the eval harness honours for its own LLM config.
#: The harness is offline evaluation infrastructure — it must not read or
#: write the user's per-agent DB settings. These vars let an operator point
#: the harness at any provider (including OpenAI-compatible endpoints) without
#: touching production configuration.
_EVAL_PROVIDER = "CORAXIS_EVAL_LLM_PROVIDER"
_EVAL_MODEL = "CORAXIS_EVAL_LLM_MODEL"
_EVAL_BASE_URL = "CORAXIS_EVAL_LLM_BASE_URL"
_EVAL_API_KEY = "CORAXIS_EVAL_LLM_API_KEY"


def _eval_llm_config(agent_slug: str) -> LLMConfig:
    """Resolve one agent's LLM config from environment variables.

    Defaults fall back to Groq so existing behaviour is unchanged when none of
    the vars are set. For an OpenAI-compatible key (e.g. Inception Labs), set:

        CORAXIS_EVAL_LLM_PROVIDER=custom
        CORAXIS_EVAL_LLM_MODEL=<model id>
        CORAXIS_EVAL_LLM_BASE_URL=https://api.inceptionlabs.ai/v1
        CORAXIS_EVAL_LLM_API_KEY=<key>
    """
    provider = os.environ.get(_EVAL_PROVIDER, "groq") or "groq"
    model = os.environ.get(_EVAL_MODEL, "") or ""
    api_key = os.environ.get(_EVAL_API_KEY, "") or ""
    base_url = os.environ.get(_EVAL_BASE_URL, "") or ""
    # Fall back to the provider key already configured in .env (read through
    # pydantic-settings env_file) when the eval-specific env var is absent.
    if not api_key.strip():
        from coraxis.core.config import get_settings

        api_key = get_settings().providers.key_for(provider) or ""
    return LLMConfig(
        agent_slug=agent_slug,
        provider=provider,  # type: ignore[arg-type]
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=0.2,
        max_tokens=4096,
        key_source="eval-env",
        # OpenAI-compatible providers such as Inception/Mercury reject unknown
        # kwargs like `drop_params`, so disable it for the eval harness.
        drop_params=False,
    )


class BaselineBlocked(RuntimeError):
    """The pipeline cannot be executed in this environment (no LLM / no network)."""


@dataclass
class CaseRecord:
    """One captured benchmark case, ready for JSON serialisation."""

    question_id: str
    question: str
    category: str
    research_plan: str = ""
    search_queries: list[str] = field(default_factory=list)
    retrieved_sources: list[dict[str, Any]] = field(default_factory=list)
    extraction_failures: list[str] = field(default_factory=list)
    intermediate_outputs: dict[str, Any] = field(default_factory=dict)
    final_report: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    execution_seconds: float = 0.0
    automatic_metrics: dict[str, float | int] = field(default_factory=dict)
    rubric: dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "question": self.question,
            "category": self.category,
            "research_plan": self.research_plan,
            "search_queries": self.search_queries,
            "retrieved_sources": self.retrieved_sources,
            "extraction_failures": self.extraction_failures,
            "intermediate_outputs": self.intermediate_outputs,
            "final_report": self.final_report,
            "citations": self.citations,
            "claims": self.claims,
            "execution_seconds": self.execution_seconds,
            "automatic_metrics": self.automatic_metrics,
            "rubric": self.rubric,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CaseRecord:
        return cls(**data)


class EvaluationHarness:
    """Runs and evaluates benchmark cases against the pipeline."""

    def __init__(
        self,
        baseline_dir: str | Path = "evaluation/baseline",
        *,
        max_sources: int = 8,
        max_fetch_per_query: int = 5,
    ) -> None:
        self.baseline_dir = Path(baseline_dir)
        self.max_sources = max_sources
        self.max_fetch_per_query = max_fetch_per_query
        self.baseline_dir.mkdir(parents=True, exist_ok=True)

    # ── Running the pipeline ──────────────────────────────────────────

    async def _built_in_specs(self) -> list[AgentSpec]:
        """Resolve the four built-in agents from the database.

        Mirrors :meth:`coraxis.services.research.ResearchOrchestrator._resolve_specs`
        but without requiring a user or team — built-in definitions have
        ``user_id IS NULL``.
        """
        from coraxis.db.session import session_scope
        from coraxis.repositories import agents as agent_repo

        async with session_scope() as session:
            definitions = await agent_repo.list_definitions(
                session,
                user_id=None,  # type: ignore[arg-type]
            )
        by_slug = {definition.slug: definition for definition in definitions}
        missing = [
            slug
            for slug in ("researcher", "web_searcher", "analyst", "summarizer")
            if slug not in by_slug
        ]
        if missing:
            raise BaselineBlocked(
                f"Built-in agents missing from database: {missing}. Run "
                "`alembic upgrade head` to seed them."
            )
        return [
            AgentSpec(
                slug=by_slug[slug].slug,
                name=by_slug[slug].name,
                role=by_slug[slug].role,
                goal=by_slug[slug].goal,
                backstory=by_slug[slug].backstory,
                tools=tuple(by_slug[slug].tools or []),
                llm=_eval_llm_config(slug),
            )
            for slug in ("researcher", "web_searcher", "analyst", "summarizer")
        ]

    async def run_case(
        self,
        question: BenchmarkQuestion,
        *,
        run_id: str | None = None,
    ) -> CaseRecord:
        """Execute the four-agent pipeline against one benchmark question.

        Returns a :class:`CaseRecord` with every intermediate output captured.

        Raises :class:`BaselineBlocked` if no LLM provider is configured or
        the pipeline cannot be started. No output is fabricated.
        """
        settings = get_settings()
        if run_id is None:
            run_id = f"eval-{question.id}"

        token = run_id_var.set(run_id)
        started = time.perf_counter()
        tracker = CitationTracker()
        fetcher = PageFetcher(
            timeout=float(settings.http_timeout_seconds),
            min_word_count=int(settings.min_word_count),
        )

        search_queries: list[str] = []
        extraction_failures: list[str] = []
        intermediate_outputs: dict[str, Any] = {}

        context = ToolContext(
            tracker=tracker,
            search=SearchClient(max_results=self.max_sources),
            fetcher=fetcher,
            run_id=run_id,
            emit=self._emit_capture(
                question_id=question.id,
                search_queries=search_queries,
                extraction_failures=extraction_failures,
                intermediate_outputs=intermediate_outputs,
            ),
        )

        try:
            specs = await self._built_in_specs()
            crew = build_pipeline_crew(
                specs,
                context,
                max_sources=self.max_sources,
                max_fetch_per_query=self.max_fetch_per_query,
            )
            # Run the synchronous kickoff in a worker thread so each case gets
            # an isolated event loop. CrewAI's async path raises ``Event loop is
            # closed`` on Windows (ProactorEventLoop) during teardown, losing a
            # fully completed run — the sync path avoids that entirely.
            result = await asyncio.wait_for(
                asyncio.to_thread(crew.kickoff, inputs={"query": question.question}),
                timeout=float(settings.run_timeout_seconds),
            )
        except TimeoutError as exc:  # pragma: no cover - sync path has no wait_for
            raise BaselineBlocked(f"Pipeline timed out for {question.id}") from exc
        except Exception as exc:
            raise BaselineBlocked(
                f"Pipeline could not execute for {question.id}: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            with suppress(Exception):
                await fetcher.aclose()
            with suppress(Exception):
                run_id_var.reset(token)

        report = self._parse_report(result)
        execution_seconds = round(time.perf_counter() - started, 3)

        sources = tracker.source_payload()
        claims = tracker.claim_payload()
        metrics = compute_metrics(
            sources=sources,
            claims=claims,
            report_markdown=report.markdown,
            search_queries=search_queries,
            extraction_failures=extraction_failures,
        )

        return CaseRecord(
            question_id=question.id,
            question=question.question,
            category=question.category,
            research_plan=intermediate_outputs.get("research_plan", ""),
            search_queries=search_queries,
            retrieved_sources=sources,
            extraction_failures=extraction_failures,
            intermediate_outputs=intermediate_outputs,
            final_report=report.markdown,
            citations=sources,
            claims=claims,
            execution_seconds=execution_seconds,
            automatic_metrics=metrics.to_dict(),
            notes=(
                "Captured by EvaluationHarness.run_case. "
                "Rubric scores must be added by a human reviewer."
            ),
        )

    # ── Persistence ───────────────────────────────────────────────────

    def save_case(self, record: CaseRecord) -> Path:
        """Persist one case record as JSON under the baseline directory."""
        path = self.baseline_dir / f"{record.question_id}.json"
        path.write_text(
            json.dumps(record.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return path

    def load_case(self, question_id: str) -> CaseRecord | None:
        """Load a previously captured case record, or None if absent."""
        path = self.baseline_dir / f"{question_id}.json"
        if not path.exists():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        return CaseRecord.from_dict(data)

    def list_captured(self) -> list[str]:
        """Ids of all captured case records on disk."""
        return sorted(p.stem for p in self.baseline_dir.glob("*.json"))

    # ── Comparison ────────────────────────────────────────────────────

    def compare(
        self,
        baseline: CaseRecord,
        current: CaseRecord,
    ) -> dict[str, Any]:
        """Compare two case records and return a human-readable delta."""
        bm = baseline.automatic_metrics or {}
        cm = current.automatic_metrics or {}

        def delta(key: str) -> float | None:
            b = bm.get(key)
            c = cm.get(key)
            if b is None or c is None:
                return None
            try:
                return round(float(c) - float(b), 4)
            except (TypeError, ValueError):
                return None

        return {
            "question_id": baseline.question_id,
            "execution_seconds_delta": delta("execution_seconds")
            if "execution_seconds" in bm and "execution_seconds" in cm
            else None,
            "total_sources_delta": delta("total_sources"),
            "fetch_success_rate_delta": delta("fetch_success_rate"),
            "unique_domains_delta": delta("unique_domains"),
            "domain_concentration_delta": delta("domain_concentration"),
            "citation_resolution_rate_delta": delta("citation_resolution_rate"),
            "claim_source_coverage_delta": delta("claim_source_coverage"),
            "extraction_failure_count_delta": delta("extraction_failure_count"),
            "search_query_count_delta": delta("search_query_count"),
            "baseline_metrics": bm,
            "current_metrics": cm,
        }

    # ── Internals ─────────────────────────────────────────────────────

    @staticmethod
    def _parse_report(result: Any) -> FinalReport:
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
        except Exception:  # noqa: BLE001 - final fallback to raw markdown
            pass
        return FinalReport(
            markdown=raw,
            executive_summary="",
            key_findings=[],
            citations_markdown="",
            stats=ReportStats(),
        )

    @staticmethod
    def _emit_capture(
        *,
        question_id: str,
        search_queries: list[str],
        extraction_failures: list[str],
        intermediate_outputs: dict[str, Any],
    ):
        def emit(event_type: str, payload: dict[str, Any] | None = None) -> None:
            payload = dict(payload or {})
            detail = str(payload.get("detail", "") or "")
            if event_type == "tool.started" and payload.get("tool") == "web_search":
                search_queries.append(detail)
            if event_type == "tool.completed":
                tool = payload.get("tool")
                detail_l = detail.lower()
                if tool == "fetch_page" and ("failed" in detail_l or "error" in detail_l):
                    extraction_failures.append(detail)
                if tool == "web_search":
                    intermediate_outputs.setdefault("search_completed", []).append(detail)
                if tool == "fetch_page":
                    intermediate_outputs.setdefault("fetch_completed", []).append(detail)
            if event_type == "claim.registered":
                intermediate_outputs.setdefault("claims", []).append(
                    {"ref": payload.get("claim_ref"), "detail": detail}
                )

        return emit
