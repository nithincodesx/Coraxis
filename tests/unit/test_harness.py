"""Tests for the evaluation harness.

The harness must not fabricate pipeline output. When no LLM provider is
available, :meth:`EvaluationHarness.run_case` raises :class:`BaselineBlocked`
with a clear message. Case persistence and comparison must work on synthetic
records without touching the network or an LLM.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from coraxis.evaluation.harness import BaselineBlocked, CaseRecord, EvaluationHarness


def _record(question_id: str = "bench-001") -> CaseRecord:
    return CaseRecord(
        question_id=question_id,
        question="What is X?",
        category="factual",
        final_report="# Report\n\nSee [^1].\n\n[^1]: **Source** — <https://a.example>",
        automatic_metrics={
            "total_sources": 1,
            "fetch_success_rate": 1.0,
            "unique_domains": 1,
            "citation_resolution_rate": 1.0,
            "claim_source_coverage": 1.0,
            "extraction_failure_count": 0,
        },
    )


def test_harness_creates_baseline_directory(tmp_path: Path) -> None:
    harness = EvaluationHarness(baseline_dir=str(tmp_path / "baseline"))
    assert harness.baseline_dir.exists()


def test_save_and_load_case_round_trip(tmp_path: Path) -> None:
    harness = EvaluationHarness(baseline_dir=str(tmp_path / "baseline"))
    record = _record()
    path = harness.save_case(record)
    assert path.exists()

    loaded = harness.load_case("bench-001")
    assert loaded is not None
    assert loaded.question_id == "bench-001"
    assert loaded.final_report == record.final_report
    assert loaded.automatic_metrics == record.automatic_metrics


def test_load_case_unknown_returns_none(tmp_path: Path) -> None:
    harness = EvaluationHarness(baseline_dir=str(tmp_path / "baseline"))
    assert harness.load_case("bench-999") is None


def test_list_captured_returns_ids(tmp_path: Path) -> None:
    harness = EvaluationHarness(baseline_dir=str(tmp_path / "baseline"))
    harness.save_case(_record("bench-001"))
    harness.save_case(_record("bench-002"))
    assert harness.list_captured() == ["bench-001", "bench-002"]


def test_compare_produces_deltas() -> None:
    harness = EvaluationHarness(baseline_dir="__nonexistent__")
    baseline = _record("bench-001")
    baseline.automatic_metrics["total_sources"] = 3
    baseline.automatic_metrics["fetch_success_rate"] = 0.5
    current = _record("bench-001")
    current.automatic_metrics["total_sources"] = 5
    current.automatic_metrics["fetch_success_rate"] = 1.0

    delta = harness.compare(baseline, current)
    assert delta["question_id"] == "bench-001"
    assert delta["total_sources_delta"] == 2
    assert delta["fetch_success_rate_delta"] == 0.5


def test_case_record_to_dict_is_json_serializable(tmp_path: Path) -> None:
    import json

    record = _record()
    json.dumps(record.to_dict())  # must not raise


def test_run_case_raises_baseline_blocked_without_llm() -> None:
    """No LLM provider is configured in this environment, so execution is blocked.

    This is the expected outcome: the harness must surface the blocker clearly
    rather than inventing a baseline.
    """
    harness = EvaluationHarness(baseline_dir="__nonexistent__")

    from coraxis.evaluation.benchmark import find_benchmark_question

    question = find_benchmark_question("bench-001")
    assert question is not None

    with pytest.raises(BaselineBlocked):
        asyncio.run(harness.run_case(question))


def test_scoring_rubric_can_be_attached_to_case_record() -> None:
    record = _record()
    record.rubric = {
        "research_coverage": {"score": 4, "rationale": "covers all angles"},
        "source_relevance": {"score": 3, "rationale": "mostly relevant"},
    }
    assert record.rubric["research_coverage"]["score"] == 4
