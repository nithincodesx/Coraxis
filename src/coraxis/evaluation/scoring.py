"""Evaluation scoring rubric.

Nine quality dimensions, each scored 0-5 against explicit criteria. Scores are
assigned by a human reviewer against the captured pipeline output; the rubric
is deliberately strict so that a 5 requires genuine evidence-handling quality,
not merely a long, confident-sounding report.

Automatic metrics (see :mod:`coraxis.evaluation.metrics`) are computed
independently and reported alongside, but never substituted for human judgment
on dimensions that require reading the sources.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: The nine evaluation dimensions, in reporting order.
DIMENSIONS: tuple[str, ...] = (
    "research_coverage",
    "source_relevance",
    "source_diversity",
    "source_quality",
    "evidence_support",
    "citation_accuracy",
    "contradiction_handling",
    "uncertainty_handling",
    "report_usefulness",
)


@dataclass(frozen=True)
class DimensionScore:
    """A single dimension's score with the reviewer's rationale."""

    dimension: str
    score: int
    rationale: str

    def __post_init__(self) -> None:
        if not 0 <= self.score <= 5:
            raise ValueError(f"score must be 0-5, got {self.score}")


@dataclass
class ScoringRubric:
    """Human-applied scoring rubric across all nine dimensions."""

    scores: dict[str, DimensionScore] = field(default_factory=dict)

    def score(self, dimension: str, value: int, rationale: str) -> None:
        """Record or replace a dimension score."""
        self.scores[dimension] = DimensionScore(
            dimension=dimension, score=value, rationale=rationale
        )

    def get(self, dimension: str) -> DimensionScore | None:
        return self.scores.get(dimension)

    def average(self) -> float:
        """Mean across scored dimensions, or 0.0 if none are scored."""
        if not self.scores:
            return 0.0
        return sum(s.score for s in self.scores.values()) / len(self.scores)

    def completed(self) -> bool:
        return all(dim in self.scores for dim in DIMENSIONS)

    def missing(self) -> list[str]:
        return [dim for dim in DIMENSIONS if dim not in self.scores]

    def to_dict(self) -> dict[str, Any]:
        return {
            dimension: {
                "score": score.score,
                "rationale": score.rationale,
            }
            for dimension, score in self.scores.items()
        }

    @classmethod
    def empty(cls) -> ScoringRubric:
        return cls()


#: Explicit criteria for every score on every dimension. A reviewer assigns the
#: highest score whose criteria are fully met; partial credit is not given.
RUBRIC: dict[str, dict[int, str]] = {
    "research_coverage": {
        5: "Every important aspect of the question is addressed; no major angle is missing.",
        4: "All major aspects are addressed; a minor sub-angle may be lightly covered.",
        3: "Most aspects addressed, but one important angle is missing or thin.",
        2: "Only some aspects addressed; significant gaps remain.",
        1: "Minimal coverage; most of the question is unaddressed.",
        0: "No meaningful coverage of the question.",
    },
    "source_relevance": {
        5: "Nearly every retrieved source directly answers a part of the question.",
        4: "Most sources are relevant; a few are tangentially related.",
        3: "About half the sources are relevant; several are off-topic.",
        2: "Few sources are relevant; most are loosely related at best.",
        1: "Almost no sources are relevant.",
        0: "No sources are relevant to the question.",
    },
    "source_diversity": {
        5: "Evidence comes from several distinct domains/organizations; no single source dominates.",
        4: "Good spread across sources; one domain may be slightly over-represented.",
        3: "Some diversity, but one or two sources carry most of the weight.",
        2: "Heavy reliance on one or two sources.",
        1: "Nearly all evidence from a single source or domain.",
        0: "No sources, or all from one source.",
    },
    "source_quality": {
        5: "Sources are predominantly primary or authoritative (official docs, peer-reviewed, government).",
        4: "Mostly credible sources with one or two weaker ones clearly flagged.",
        3: "Mix of credible and lower-quality sources without clear distinction.",
        2: "Mostly low-quality or aggregator sources.",
        1: "Almost no credible sources.",
        0: "No sources.",
    },
    "evidence_support": {
        5: "Every factual claim is backed by at least one retrieved source; unsupported claims are explicitly flagged.",
        4: "Nearly all claims are supported; one or two minor claims lack a source.",
        3: "Most claims supported, but several important claims lack evidence.",
        2: "Many claims unsupported; evidence is thin for key points.",
        1: "Almost no claims trace to evidence.",
        0: "No claims are supported by evidence.",
    },
    "citation_accuracy": {
        5: "Every inline citation resolves to a real retrieved source that supports the claim; no invented citations.",
        4: "Citations are accurate; one minor mismatch between claim and source.",
        3: "Mostly accurate, but several citations are weak or loosely related.",
        2: "Citations frequently do not match the claims they accompany.",
        1: "Mostly invented or mismatched citations.",
        0: "No valid citations.",
    },
    "contradiction_handling": {
        5: "Conflicting evidence is explicitly identified, attributed to specific sources, and the conflict is explained rather than hidden.",
        4: "Contradictions are noted, but attribution or explanation is thin.",
        3: "Some conflicts are visible but not clearly resolved or attributed.",
        2: "Conflicting sources are presented without acknowledging they disagree.",
        1: "Contradictions are silently resolved (one side dropped).",
        0: "No attempt to handle conflicting evidence.",
    },
    "uncertainty_handling": {
        5: "Insufficient or conflicting evidence is stated plainly; no claim overstates what the sources support.",
        4: "Uncertainty is acknowledged for most weak claims.",
        3: "Some uncertainty is acknowledged, but weak claims are sometimes stated as fact.",
        2: "Uncertainty is rarely acknowledged; thin evidence is presented confidently.",
        1: "Nearly everything is stated as fact regardless of evidence strength.",
        0: "No uncertainty handling at all.",
    },
    "report_usefulness": {
        5: "Clear, well-structured, decision-ready; executive summary, findings, and limitations all present.",
        4: "Well organized and useful; one section could be clearer.",
        3: "Useful but has noticeable organizational or clarity issues.",
        2: "Some useful content, but difficult to use as-is.",
        1: "Barely useful; mostly unstructured or repetitive.",
        0: "Not useful.",
    },
}


def criteria_for(dimension: str, score: int) -> str:
    """Return the rubric text for one dimension/score pair."""
    return RUBRIC[dimension][score]


@dataclass
class EvaluationResult:
    """One benchmark case's complete evaluation record."""

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
    execution_seconds: float = 0.0
    automatic_metrics: dict[str, float] = field(default_factory=dict)
    rubric: ScoringRubric = field(default_factory=ScoringRubric.empty)
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
            "execution_seconds": self.execution_seconds,
            "automatic_metrics": self.automatic_metrics,
            "rubric": self.rubric.to_dict(),
            "rubric_average": self.rubric.average(),
            "rubric_completed": self.rubric.completed(),
            "notes": self.notes,
        }
