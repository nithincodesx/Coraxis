"""Run one benchmark case with real-time output for timing measurement."""

from __future__ import annotations

import asyncio
import os
import sys
import time

os.environ.setdefault("CORAXIS_SECRET_KEY", "baseline-secret-key-long-enough-for-validation")
os.environ.setdefault("CORAXIS_ENV", "development")
os.environ.setdefault("CORAXIS_FIREBASE_PROJECT_ID", "baseline-project")
os.environ.setdefault("CORAXIS_DATABASE_URL", "sqlite+aiosqlite:///./data/baseline.db")
os.environ.setdefault("CORAXIS_CHROMA_PATH", "./chroma_db")
os.environ.setdefault("CORAXIS_MEMORY_ENABLED", "false")
os.environ.setdefault("CORAXIS_RATE_LIMIT_ENABLED", "false")
os.environ.setdefault("CORAXIS_LOG_LEVEL", "WARNING")
os.environ.setdefault("CORAXIS_RUN_TIMEOUT_SECONDS", "180")

os.environ.setdefault("CORAXIS_EVAL_LLM_PROVIDER", "custom")
os.environ.setdefault("CORAXIS_EVAL_LLM_MODEL", "mercury-3")
os.environ.setdefault("CORAXIS_EVAL_LLM_BASE_URL", "https://api.inceptionlabs.ai/v1")

from coraxis.core.config import reset_settings_cache
from coraxis.db.session import create_all, dispose_engine
from coraxis.evaluation.benchmark import find_benchmark_question
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
    question_id = sys.argv[1] if len(sys.argv) > 1 else "bench-001"
    question = find_benchmark_question(question_id)
    if question is None:
        print(f"Unknown question id: {question_id}", flush=True)
        return
    print(f"Running {question.id}...", flush=True)
    t0 = time.perf_counter()
    try:
        record = await harness.run_case(question)
        harness.save_case(record)
        dt = time.perf_counter() - t0
        m = record.automatic_metrics
        print(
            f"DONE {question.id} in {dt:.1f}s | "
            f"sources={m.get('total_sources')} fetch={m.get('fetch_success_rate')} "
            f"domains={m.get('unique_domains')} cite_res={m.get('citation_resolution_rate')} "
            f"claim_src={m.get('claim_source_coverage')} failures={m.get('extraction_failure_count')}",
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        dt = time.perf_counter() - t0
        print(f"BLOCKED {question.id} after {dt:.1f}s: {type(exc).__name__}: {exc}", flush=True)

    await dispose_engine()


if __name__ == "__main__":
    asyncio.run(main())
