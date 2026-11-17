"""Research quality evaluation framework.

This package is intentionally *not* imported by any API route or production
execution path. It exists only to support reproducible offline evaluation of
the research pipeline, so benchmarking can never leak into a user's request.

Public surface:
- :data:`BENCHMARK` - fixed list of :class:`BenchmarkQuestion` instances.
- :class:`ScoringRubric` - 0-5 scoring across nine quality dimensions.
- :class:`EvaluationHarness` - runs benchmark cases and compares results.
- :mod:`coraxis.evaluation.metrics` - automatic, reproducible metrics.
"""

from __future__ import annotations

from .benchmark import BENCHMARK, BenchmarkQuestion
from .harness import EvaluationHarness
from .scoring import DimensionScore, EvaluationResult, ScoringRubric

__all__ = [
    "BENCHMARK",
    "BenchmarkQuestion",
    "DimensionScore",
    "EvaluationHarness",
    "EvaluationResult",
    "ScoringRubric",
]
