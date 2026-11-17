"""Tests for the scoring rubric.

Scores must be clamped to 0-5, averages must be computed only over scored
dimensions, and the rubric text must exist for every dimension/score pair.
"""

from __future__ import annotations

from coraxis.evaluation.scoring import (
    DIMENSIONS,
    DimensionScore,
    EvaluationResult,
    ScoringRubric,
    criteria_for,
)


def test_dimension_score_clamts_to_valid_range() -> None:
    with __import__("pytest").raises(ValueError):
        DimensionScore(dimension="research_coverage", score=6, rationale="x")
    with __import__("pytest").raises(ValueError):
        DimensionScore(dimension="research_coverage", score=-1, rationale="x")


def test_rubric_average_is_zero_when_nothing_scored() -> None:
    assert ScoringRubric.empty().average() == 0.0


def test_rubric_average_is_mean_over_scored_dimensions() -> None:
    rubric = ScoringRubric.empty()
    rubric.score("research_coverage", 4, "good coverage")
    rubric.score("source_relevance", 2, "some misses")
    assert rubric.average() == 3.0


def test_rubric_completed_requires_all_dimensions() -> None:
    rubric = ScoringRubric.empty()
    assert not rubric.completed()
    for dimension in DIMENSIONS:
        rubric.score(dimension, 3, "placeholder")
    assert rubric.completed()


def test_rubric_missing_lists_unscored_dimensions() -> None:
    rubric = ScoringRubric.empty()
    rubric.score("research_coverage", 3, "x")
    assert "source_relevance" in rubric.missing()
    assert "research_coverage" not in rubric.missing()


def test_every_dimension_has_criteria_for_every_score() -> None:
    for dimension in DIMENSIONS:
        for score in range(6):
            text = criteria_for(dimension, score)
            assert text, f"missing criteria for {dimension}/{score}"


def test_evaluation_result_to_dict_includes_rubric_average() -> None:
    result = EvaluationResult(
        question_id="bench-001",
        question="What is X?",
        category="factual",
    )
    result.rubric.score("research_coverage", 4, "covers everything")
    d = result.to_dict()
    assert d["rubric_average"] == 4.0
    assert d["rubric_completed"] is False
    assert d["question_id"] == "bench-001"
