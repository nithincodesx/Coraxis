"""Tests for the fixed research benchmark.

These tests verify that the benchmark is well-formed, complete, and
self-consistent. They do not assert on research answers — they assert on the
benchmark's structure so that future changes cannot silently degrade it.
"""

from __future__ import annotations

from coraxis.evaluation.benchmark import (
    BENCHMARK,
    benchmark_by_category,
    categories,
    find_benchmark_question,
    to_dict,
)


def test_benchmark_has_expected_count() -> None:
    assert len(BENCHMARK) == 10


def test_benchmark_covers_all_required_categories() -> None:
    expected = {
        "factual",
        "technical",
        "comparative",
        "multipart",
        "conflicting",
        "time-sensitive",
        "primary-source",
        "insufficient-evidence",
    }
    found = set(categories())
    assert expected.issubset(found), f"missing categories: {expected - found}"


def test_every_question_has_required_fields() -> None:
    for question in BENCHMARK:
        assert question.id
        assert question.question
        assert question.category
        assert question.expected_coverage
        assert question.subquestions
        assert question.expected_evidence_types
        assert question.authoritative_sources
        assert question.common_failure_modes
        assert question.evaluation_criteria


def test_every_question_has_at_least_two_subquestions() -> None:
    for question in BENCHMARK:
        assert len(question.subquestions) >= 2, question.id


def test_find_benchmark_question_round_trips() -> None:
    for question in BENCHMARK:
        assert find_benchmark_question(question.id) is question


def test_find_benchmark_question_unknown_returns_none() -> None:
    assert find_benchmark_question("bench-999") is None


def test_benchmark_by_category_filters() -> None:
    time_sensitive = benchmark_by_category("time-sensitive")
    assert len(time_sensitive) >= 2
    assert all(q.category == "time-sensitive" for q in time_sensitive)


def test_insufficient_evidence_question_is_flagged() -> None:
    q = find_benchmark_question("bench-010")
    assert q is not None
    assert q.category == "insufficient-evidence"
    # The system should not be expected to invent an answer to an unknowable question.
    assert any(
        "unknowable" in c.lower() or "not yet known" in c.lower() for c in q.evaluation_criteria
    )


def test_to_dict_is_json_serializable() -> None:
    import json

    for question in BENCHMARK:
        payload = to_dict(question)
        json.dumps(payload)  # must not raise


def test_time_sensitive_questions_record_benchmark_date() -> None:
    for question in BENCHMARK:
        if question.time_sensitive:
            assert question.benchmark_date is not None, question.id
