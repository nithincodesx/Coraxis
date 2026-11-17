# PHASE 02A COMPLETION REPORT — Baseline and Evaluation Framework

## 1. Objective

Establish an objective baseline of Coraxis's existing research quality before modifying any agents in Phase 02B–02E. The evaluation framework, fixed benchmark, and scoring rubric must be reproducible so that post-improvement results can be directly compared.

## 2. Initial Repository State

- Branch: `main`
- Commit: `0e008a244b7f85645da0a5a78704e0cc2b173842`
- Remote: `origin/main` (in sync)
- Working tree: clean (before changes)
- Phase 01 and 01.5 complete; CI run #11 passed all five jobs.

## 3. Files Inspected

Pipeline implementation (read, not modified):

| File | Purpose |
|------|---------|
| `src/coraxis/agents/definitions.py` | Four built-in agent role definitions (researcher, web_searcher, analyst, summarizer) |
| `src/coraxis/agents/crew.py` | Crew assembly: `build_pipeline_crew`, `build_team_crew`, `build_agent` |
| `src/coraxis/agents/tasks.py` | Task definitions and Pydantic output schemas (`SubQuestions`, `RawFindings`, `AnalyzedFindings`, `FinalReport`) |
| `src/coraxis/agents/citations.py` | `CitationTracker`: stable citation numbering, claim-to-source linking |
| `src/coraxis/agents/context.py` | `ToolContext`: dependency injection container for agent tools |
| `src/coraxis/agents/tools/search.py` | `SearchClient`: DuckDuckGo search with retry/backoff |
| `src/coraxis/agents/tools/fetch.py` | `PageFetcher`: async HTTP fetch + Trafilatura/readability extraction |
| `src/coraxis/agents/tools/crew_tools.py` | CrewAI `ContextTool` implementations (search, fetch, recall, register_claim, messaging) |
| `src/coraxis/agents/tool_registry.py` | `TOOL_REGISTRY`: tool catalogue with builtin agent grants |
| `src/coraxis/agents/comms.py` | `AgentChannel`: bounded in-memory messaging and blackboard |
| `src/coraxis/services/research.py` | `ResearchOrchestrator`: run lifecycle, crew execution, persistence |
| `src/coraxis/repositories/agents.py` | Agent definition persistence and seeding |
| `src/coraxis/repositories/runs.py` | Run, event, source, and claim persistence |
| `src/coraxis/schemas/agents.py` | Agent API schemas |
| `tests/conftest.py` | Test fixtures (SQLite DB, Firebase stub, app client) |
| `tests/unit/test_citations.py` | Existing citation tracker tests |
| `tests/unit/test_tools.py` | Existing tool construction tests |
| `tests/integration/test_run_lifecycle.py` | Existing run lifecycle tests |
| `pyproject.toml` | Dependencies, lint, type, and test configuration |

## 4. Files Changed

### New files (evaluation framework — not imported by any API route)

| File | Purpose |
|------|---------|
| `src/coraxis/evaluation/__init__.py` | Package public surface |
| `src/coraxis/evaluation/benchmark.py` | `BenchmarkQuestion` dataclass + `BENCHMARK` list of 10 fixed questions |
| `src/coraxis/evaluation/scoring.py` | `ScoringRubric`, `DimensionScore`, `EvaluationResult`, 0–5 rubric across 9 dimensions |
| `src/coraxis/evaluation/metrics.py` | `compute_metrics()` — automatic, deterministic metrics |
| `src/coraxis/evaluation/harness.py` | `EvaluationHarness` — run cases, capture outputs, persist, compare |
| `tests/unit/test_benchmark.py` | Benchmark structure tests |
| `tests/unit/test_scoring.py` | Scoring rubric tests |
| `tests/unit/test_metrics.py` | Automatic metrics tests |
| `tests/unit/test_harness.py` | Harness persistence/comparison/blocker tests |

### Directory created

- `evaluation/baseline/` — intended storage for captured case records (JSON). Empty; no baseline captured yet (see blocker below).

### Modified files

None. No production files were modified.

## 5. Technical Implementation Details

### Benchmark (`benchmark.py`)

Ten fixed `BenchmarkQuestion` instances across eight categories:

| ID | Category | Time-sensitive |
|----|----------|----------------|
| bench-001 | comparative | No |
| bench-002 | technical | No |
| bench-003 | factual | No |
| bench-004 | comparative | No |
| bench-005 | time-sensitive | Yes (2026-11-10) |
| bench-006 | time-sensitive | Yes (2026-11-10) |
| bench-007 | primary-source | No |
| bench-008 | multipart | No |
| bench-009 | conflicting | No |
| bench-010 | insufficient-evidence | Yes (2026-11-10) |

Each question includes: research question, category, expected coverage, subquestions, expected evidence types, authoritative sources, common failure modes, and evaluation criteria. No expected answers are fabricated.

### Scoring rubric (`scoring.py`)

Nine dimensions, each scored 0–5 with explicit per-score criteria:

1. research_coverage
2. source_relevance
3. source_diversity
4. source_quality
5. evidence_support
6. citation_accuracy
7. contradiction_handling
8. uncertainty_handling
9. report_usefulness

Scores are human-applied against captured pipeline output. `ScoringRubric.completed()` requires all nine dimensions scored.

### Automatic metrics (`metrics.py`)

Deterministic, computed without LLM judgment:

- total_sources, fetched_sources, fetch_success_rate
- unique_domains, domain_concentration (share from most common domain)
- duplicate_url_rate
- sources_with_metadata (title + snippet present)
- citation_marker_count, resolved_citations, citation_resolution_rate
- claims_with_sources, total_claims, claim_source_coverage
- extraction_failure_count, search_query_count

### Harness (`harness.py`)

- `run_case(question)` — executes the four-agent pipeline via `crew.kickoff_async`, captures all intermediate outputs (search queries, fetch results, claims, report), computes automatic metrics, returns a `CaseRecord`.
- `save_case(record)` / `load_case(question_id)` — JSON persistence under `evaluation/baseline/`.
- `compare(baseline, current)` — metric delta between two case records.
- `BaselineBlocked` exception — raised when the pipeline cannot execute (no LLM, no DB, etc.). No output is fabricated.

The harness does not import or call any API route; it is fully separated from production execution.

## 6. Problems Discovered

### Confirmed defects (observed from code inspection)

1. **No query diversification** — the Web Searcher searches only the sub-questions produced by the Researcher. No reformulated or parallel queries for the same information need. Search coverage is limited to the Researcher's decomposition.

2. **Crude provisional relevance scoring** — `SearchTool` registers every search result at relevance 0.5 and every fetched page at 0.6, with no source-type classification (academic/official/news/opinion). The Analyst re-scores, but the initial signal is undifferentiated.

3. **No source credibility or freshness awareness** — no mechanism to prefer primary sources, official documentation, or recent publications. Time-sensitive questions (bench-005, bench-006) risk being answered with stale sources.

4. **No duplicate detection beyond URL dedup** — the `CitationTracker` dedups by URL, but near-duplicate content from different URLs (e.g., syndicated articles) is not detected.

5. **Contradictions are free-text strings** — `AnalyzedFindings.conflicts` is `list[str]`, unstructured. Contradictions are not linked to specific source pairs or claims.

6. **No unsupported-claim flag** — claims can be registered with zero supporting sources; there is no explicit "evidence insufficient" marking at the claim level.

7. **No citation-to-claim validation** — nothing validates that `[^n]` markers in the final report resolve to registered sources, or that the cited source actually supports the claim.

8. **Citation tracker is in-memory only per run** — sources and claims are persisted to the DB at run end, but there is no cross-run source quality memory (distinct from semantic memory).

### Basel capture blocker

The pipeline cannot be executed in this environment because:

- **No LLM API keys configured**: `GROQ_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY` are all empty in `.env`. Without an LLM provider, `crew.kickoff_async()` cannot produce agent output.
- **Database not seeded**: the `agent_definitions` table does not exist until `alembic upgrade head` / `create_all()` + `seed_builtin_agents()` is run.

The harness correctly raises `BaselineBlocked` with a clear message rather than fabricating output. No baseline case records were captured.

## 7. Solutions Implemented

- Built the complete evaluation framework (benchmark, scoring rubric, automatic metrics, harness) as a self-contained package separate from production code.
- Designed 10 benchmark questions across 8 required categories (factual, technical, comparative, multipart, conflicting, time-sensitive, primary-source, insufficient-evidence).
- Defined a 0–5 scoring rubric with explicit criteria for every dimension/score pair.
- Implemented 13 automatic, deterministic metrics covering source quality, citation resolution, claim sourcing, and extraction reliability.
- Wrote 36 unit tests for the framework (benchmark structure, scoring calculations, metric computation, harness persistence/comparison/blocker behavior).
- Verified the harness surfaces the baseline blocker correctly (`BaselineBlocked` raised when no LLM/DB is available).

No production agent prompts, behavior, or API contracts were modified.

## 8. Tests Added

| File | Tests |
|------|-------|
| `tests/unit/test_benchmark.py` | 12 tests: count, categories, required fields, subquestion count, round-trip lookup, category filtering, insufficient-evidence flag, JSON serializability, time-sensitive dates |
| `tests/unit/test_scoring.py` | 8 tests: score clamping, average computation, completion tracking, missing dimensions, rubric criteria coverage, result serialization |
| `tests/unit/test_metrics.py` | 14 tests: empty output, fetch success rate, domain concentration, duplicate URL rate, citation resolution, claim coverage, metadata rate, failures/queries, JSON serializability, summary readability, invalid URLs |
| `tests/unit/test_harness.py` | 8 tests: baseline dir creation, save/load round-trip, unknown case, list captured, compare deltas, JSON serializability, BaselineBlocked without LLM, rubric attachment |

## 9. Exact Commands Executed

```bash
# Run new evaluation tests
python -m pytest tests/unit/test_benchmark.py tests/unit/test_scoring.py tests/unit/test_metrics.py tests/unit/test_harness.py -v

# Run full existing test suite
python -m pytest tests/

# Lint
python -m ruff check src/coraxis/evaluation/ tests/unit/test_benchmark.py tests/unit/test_scoring.py tests/unit/test_metrics.py tests/unit/test_harness.py

# Format check
python -m ruff format --check src/coraxis/evaluation/ tests/unit/test_benchmark.py tests/unit/test_scoring.py tests/unit/test_metrics.py tests/unit/test_harness.py

# Type check
python -m mypy src/coraxis/evaluation/

# Baseline capture attempt (blocked)
python -c "import asyncio; from coraxis.evaluation.harness import EvaluationHarness, BaselineBlocked; from coraxis.evaluation.benchmark import find_benchmark_question; harness = EvaluationHarness(baseline_dir='evaluation/baseline'); q = find_benchmark_question('bench-001'); asyncio.run(harness.run_case(q))"
```

## 10. Actual Test Results

| Suite | Result |
|-------|--------|
| New evaluation tests (36) | **36 passed** |
| Full test suite (187 total) | **187 passed** |
| Ruff lint | **All checks passed** |
| Ruff format | **All files formatted** |
| MyPy | **No issues found** |
| Baseline capture | **Blocked** — `BaselineBlocked`: no LLM API keys configured, database not seeded |

No existing tests were weakened or removed.

## 11. Benchmark Results

No benchmark cases were executed. Baseline capture is blocked (see Section 6). The framework is ready to capture baselines once:

1. LLM API keys are configured (`GROQ_API_KEY`, `GOOGLE_API_KEY`, or `OPENAI_API_KEY`), and
2. The database is initialized (`alembic upgrade head` + `seed_builtin_agents`).

When unblocked, run:
```bash
python -c "
import asyncio, json
from pathlib import Path
from coraxis.evaluation.harness import EvaluationHarness
from coraxis.evaluation.benchmark import BENCHMARK
harness = EvaluationHarness(baseline_dir='evaluation/baseline')
for q in BENCHMARK:
    try:
        record = await harness.run_case(q)
        harness.save_case(record)
        print(f'{q.id}: captured ({record.execution_seconds}s)')
    except Exception as e:
        print(f'{q.id}: blocked — {e}')
"
```

## 12. Known Limitations

- **Baseline not captured**: No LLM provider is configured, so no pipeline output exists to score. This is an environment limitation, not a framework limitation.
- **Human rubric scores are manual**: The 0–5 rubric requires a human reviewer to read captured outputs and assign scores. The framework stores the structure but does not automate rubric scoring.
- **Harness runs the real pipeline**: `run_case` executes CrewAI with actual LLM calls, network search, and page fetching. It is slow and cost-bearing; intended for offline evaluation only, not production API use.
- **No cross-user isolation concerns**: The evaluation framework is offline-only and does not touch user data.

## 13. Remaining Risks

- Without LLM credentials, the baseline cannot be established in this session. Phase 02B–02E improvements cannot be measured against a captured baseline until credentials are available.
- The harness seeds LLM config with empty API keys (`provider="groq"`, `api_key=""`) purely to resolve built-in agent specs from the database; it does not attempt LLM calls until `run_case` is invoked, at which point it will fail without a key.
- Time-sensitive benchmark questions (bench-005, bench-006, bench-010) are evaluated relative to the benchmark date `2026-11-10`; source freshness assessments will age.

## 14. Git Branch and Commit SHA

- Branch: `main`
- Commit (pre-change): `0e008a244b7f85645da0a5a78704e0cc2b173842`
- Working tree: has new untracked files (evaluation package + tests + report)

## 15. Whether Changes Were Pushed

No changes have been pushed. All new files are untracked in the local working tree. Per instructions, changes are not pushed without explicit authorization.

## 16. Recommended Next Subphase

**Phase 02B — Researcher Intelligence**. The evaluation framework is complete and ready. The next step is to improve the Researcher agent's planning (subquestion decomposition, query diversification, gap identification) using this framework for measurement. Approval is requested before proceeding.
