"""Capture Phase 02A baseline across all benchmark questions.

Sets the eval LLM env vars for an OpenAI-compatible provider (Inception /
Mercury 3), seeds the database, runs every benchmark question through the
real pipeline, and stores case records under evaluation/baseline/.

The API key is read from the environment only — never hardcoded here.
"""

from __future__ import annotations

import asyncio
import os

# ── Point the app at a throwaway dev DB and disable slow bits ──────────
os.environ.setdefault("CORAXIS_SECRET_KEY", "baseline-secret-key-long-enough-for-validation")
os.environ.setdefault("CORAXIS_ENV", "development")
os.environ.setdefault("CORAXIS_FIREBASE_PROJECT_ID", "baseline-project")
os.environ.setdefault("CORAXIS_DATABASE_URL", "sqlite+aiosqlite:///./data/baseline.db")
os.environ.setdefault("CORAXIS_CHROMA_PATH", "./chroma_db")
os.environ.setdefault("CORAXIS_MEMORY_ENABLED", "false")
os.environ.setdefault("CORAXIS_RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("CORAXIS_LOG_LEVEL", "WARNING")
os.environ.setdefault("CORAXIS_RUN_TIMEOUT_SECONDS", "180")

# ── Eval LLM: OpenAI-compatible (Inception Labs / Mercury 3) ───────────
os.environ.setdefault("CORAXIS_EVAL_LLM_PROVIDER", "custom")
os.environ.setdefault("CORAXIS_EVAL_LLM_MODEL", "mercury-3")
os.environ.setdefault("CORAXIS_EVAL_LLM_BASE_URL", "https://api.inceptionlabs.ai/v1")
# API key must already be in the environment: CORAXIS_EVAL_LLM_API_KEY

from coraxis.core.config import reset_settings_cache
from coraxis.db.session import create_all, dispose_engine
from coraxis.evaluation.benchmark import BENCHMARK
from coraxis.evaluation.harness import EvaluationHarness
from coraxis.services.bootstrap import seed_builtin_agents


async def main() -> None:
    reset_settings_cache()
    await create_all()
    await seed_builtin_agents()

    harness = EvaluationHarness(
        baseline_dir="evaluation/baseline",
        max_sources=3,
        max_fetch_per_query=2,
    )
    for question in BENCHMARK:
        out = harness.baseline_dir / f"{question.id}.json"
        if out.exists():
            print(
                f"=== {question.id} [{question.category}] — already captured, skipping ===",
                flush=True,
            )
            continue
        print(f"\n=== {question.id} [{question.category}] ===", flush=True)
        print(question.question[:120], flush=True)
        try:
            record = await harness.run_case(question)
            harness.save_case(record)
            m = record.automatic_metrics
            print(
                f"  sources={m.get('total_sources')} "
                f"fetch={m.get('fetch_success_rate')} "
                f"domains={m.get('unique_domains')} "
                f"cite_res={m.get('citation_resolution_rate')} "
                f"claim_src={m.get('claim_source_coverage')} "
                f"failures={m.get('extraction_failure_count')} "
                f"{record.execution_seconds}s",
                flush=True,
            )
        except Exception as exc:  # noqa: BLE001 - keep capturing the rest
            print(f"  BLOCKED: {type(exc).__name__}: {exc}")

    await dispose_engine()
    print("\nBaseline capture complete. Records in evaluation/baseline/")


if __name__ == "__main__":
    asyncio.run(main())
