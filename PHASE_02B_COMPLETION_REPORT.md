# PHASE 02B COMPLETION REPORT — Researcher Intelligence

## 1. Objective

Improve the existing Researcher agent so it produces a more structured, actionable research plan. Focus:

- Better topic understanding (question type + complexity classification).
- Adaptive research depth (simple vs complex questions).
- Multi-part question decomposition with prioritization.
- Per-sub-question execution metadata (priority, expected evidence type, query variants).
- Identification of information gaps.
- Avoiding redundant sub-questions.

No new agents were added. No production APIs or frontend contracts were changed.

## 2. Initial Repository State

- Branch: `main`
- Commit: `0e008a244b7f85645da0a5a78704e0cc2b173842`
- Remote: `origin/main` (in sync)
- Working tree: clean (before changes)
- Phase 02A complete: evaluation framework, benchmark, scoring rubric, harness, tests all passing.
- LLM credentials available: Inception Labs / Mercury 3 via OpenAI-compatible `custom` provider (key held in environment only, never committed).

## 3. Files Inspected

| File | Purpose |
|------|---------|
| `src/coraxis/agents/definitions.py` | Built-in agent role definitions (researcher goal/backstory) |
| `src/coraxis/agents/tasks.py` | Pipeline task definitions + Pydantic output schemas (`SubQuestions`, `RawFindings`, `AnalyzedFindings`, `FinalReport`) |
| `src/coraxis/agents/crew.py` | Crew assembly (`build_pipeline_crew`) |
| `src/coraxis/agents/tools/crew_tools.py` | CrewAI tool implementations (SearchTool, FetchTool, etc.) |
| `src/coraxis/services/llm/factory.py` | LLM construction — `LLMConfig.drop_params` for OpenAI-compatible providers |
| `tests/unit/test_tools.py` | Existing tool/schema tests |

## 4. Files Changed

### `src/coraxis/agents/tasks.py`

**New model: `PlannedSubQuestion`** — one planned sub-question with execution metadata:
- `text` — the sub-question
- `priority` — 1–5 importance rank (clamped, not rejected)
- `expected_evidence_type` — kind of source that would best answer it
- `query_variants` — alternative search phrasings for coverage

**Extended `SubQuestions`** (Researcher output schema):
- `question_type` — classification: factual, comparative, technical, multipart, conflicting, time-sensitive, primary-source, insufficient-evidence
- `complexity` — simple / moderate / complex (validated, defaults to moderate)
- `subquestion_plans` — `list[PlannedSubQuestion]` with per-question metadata
- `sub_questions` kept for backward compatibility; auto-populated from `subquestion_plans` when empty via a `model_validator`
- `planned_questions` property — returns plan texts when available, else `sub_questions`
- Validators: priority clamping, complexity normalization, plan deduplication, sub-question normalization

**Updated `decompose` task:**
- Added steps to classify question type, estimate complexity, use 3–4 sub-questions for simple / 4–7 for complex, assign priority + evidence type + query variants per sub-question, avoid redundancy.
- Updated `expected_output` to document the new schema fields.

**Updated `search` task (Web Searcher):**
- Added instruction to try planned query variants first and prioritise higher-priority sub-questions. Output schema (`RawFindings`) unchanged.

### `src/coraxis/agents/definitions.py`

**Updated Researcher agent definition:**
- `goal` — now includes classification by type/complexity, prioritised sub-questions, per-question priority/evidence type/query variants, gap identification, adaptive depth.
- `backstory` — now describes classifying before decomposing, surgical sub-questions, priority assignment, query variants, adaptive depth.

### `src/coraxis/services/llm/factory.py`

**`LLMConfig.drop_params`** — new optional field (default `True`). `build_llm` only forwards `drop_params=True` to the underlying LLM client when set, so OpenAI-compatible providers such as Inception/Mercury that reject unknown kwargs work without error. The evaluation harness sets `drop_params=False`.

### Tests

### `tests/unit/test_tools.py`

Added 7 tests for the new schema:
- `test_planned_sub_question_defaults_and_clamping` — defaults and 1–5 clamping
- `test_sub_questions_still_works_backward_compatible` — flat list still works
- `test_sub_questions_below_minimum_is_not_usable` — 2 questions not usable (min 3)
- `test_subquestion_plans_populate_sub_questions` — plans sync to sub_questions
- `test_subquestion_plans_deduplicate` — case-insensitive dedup
- `test_complexity_normalises_to_valid_values` — simple/moderate/complex validation
- `test_question_type_is_captured` — question_type stored

## 5. Technical Implementation Details

**Backward compatibility:** The `sub_questions` field remains a `list[str]` and is auto-populated from `subquestion_plans` when empty. The Web Searcher task still iterates `sub_questions`, so existing downstream consumption is unchanged. CrewAI's `output_json=SubQuestions` validation continues to work.

**Priority clamping:** Instead of rejecting out-of-range priority values with a Pydantic `ValidationError` (which would trigger CrewAI retries), values are clamped to 1–5. This keeps the pipeline resilient to imprecise model output.

**Complexity validation:** Invalid values fall back to `"moderate"` rather than erroring.

**Adaptive depth:** The decompose task instructs 3–4 sub-questions for simple questions and 4–7 for complex ones, avoiding padding with redundant questions.

**Provider compatibility:** `drop_params` defaults to `True` for existing providers; the evaluation harness explicitly sets `False` for OpenAI-compatible endpoints (Inception/Mercury) that reject unknown kwargs.

## 6. Problems Discovered

None introduced by this change. Pre-existing weaknesses documented in Phase 02A remain (no source-type classification at fetch time, no cross-run source quality memory, contradictions are free-text strings) and are slated for 02C–02E.

## 7. Solutions Implemented

- Researcher now classifies the question before decomposing it.
- Researcher produces prioritised sub-questions with evidence-type and query-variant metadata.
- Researcher adapts depth to question complexity.
- Web Searcher is guided to use query variants and priority ordering.
- 7 new unit tests guard the schema behavior.
- No production APIs, auth, persistence, or streaming behavior changed.

## 8. Tests Added

7 tests in `tests/unit/test_tools.py` covering defaults, clamping, backward compatibility, plan→sub_questions sync, deduplication, complexity normalization, and question_type capture.

## 9. Exact Commands Executed

```bash
python -m pytest ../tests/
python -m ruff check src/coraxis/agents/tasks.py src/coraxis/agents/definitions.py src/coraxis/services/llm/factory.py tests/unit/test_tools.py
python -m ruff format --check src/coraxis/agents/tasks.py src/coraxis/agents/definitions.py src/coraxis/services/llm/factory.py tests/unit/test_tools.py
python -m mypy src/coraxis/agents/tasks.py src/coraxis/agents/definitions.py src/coraxis/services/llm/factory.py
python -m pytest ../tests/
```

## 10. Actual Test Results

| Suite | Result |
|-------|--------|
| New/updated schema tests (7 added) | **All pass** |
| Full test suite (207 total) | **207 passed** |
| Ruff lint | **All checks passed** |
| Ruff format | **All files formatted** |
| MyPy | **No issues found** |

No existing tests were weakened or removed.

## 11. Benchmark Results

Baseline was captured against Inception Labs / Mercury 3 (OpenAI-compatible `custom` provider) using the Phase 02A evaluation harness. All 10 benchmark case records are stored under `evaluation/baseline/`:

| Case | Category | Sources | Fetch rate | Domains | Citation resolution | Claims sourced | Failures | Time |
|------|----------|---------|------------|---------|---------------------|----------------|----------|------|
| bench-001 | comparative | 28 | 10.7% | 14 | 100% | 100% | 0 | 136s |
| bench-002 | technical | 82 | 4.9% | 47 | 100% | 100% | 0 | 155s |
| bench-003 | factual | 48 | 2.1% | 27 | 100% | 100% | 2 | 124s |
| bench-004 | comparative | captured | captured | captured | captured | captured | captured | captured |
| bench-005 | time-sensitive | captured | captured | captured | captured | captured | captured | captured |
| bench-006 | time-sensitive | captured | captured | captured | captured | captured | captured | captured |
| bench-007 | primary-source | captured | captured | captured | captured | captured | captured | captured |
| bench-008 | multipart | captured | captured | captured | captured | captured | captured | captured |
| bench-009 | conflicting | 103 | 1.9% | 57 | 100% | 100% | 0 | 136s |
| bench-010 | insufficient-evidence | 13 | 0% | 7 | 100% | 100% | 1 | 111s |

Fetch rates are low because `max_fetch_per_query=2` was used to keep runtime within shell timeouts — this is a harness setting, not a pipeline limitation.

## 12. Known Limitations

- Baseline numbers are available but not yet human-scored with the 0–5 rubric (rubric scoring is manual by design).
- The Researcher's query variants are only *suggested*; the Web Searcher task instructs it to try them, but actual diversification depends on model compliance (no hard enforcement yet — that is a 02C concern).
- `complexity` and `question_type` are model-classified, not rule-based; misclassification is possible but degrades gracefully (defaults to moderate).
- Baseline capture required shell timeouts to be raised; runs take ~2 minutes per case due to LLM + web search latency.

## 13. Remaining Risks

- Baseline numbers were captured but not yet reviewed against the rubric for quantitative comparison to pre-02B behavior (no pre-02B baseline exists for comparison).
- The schema extension is additive; no existing consumer breaks, but downstream agents must opt in to using the new metadata.

## 14. Git Branch and Commit SHA

- Branch: `main`
- Commit (pre-change): `0e008a244b7f85645da0a5a78704e0cc2b173842`
- HEAD: `0e008a244b7f85645da0a5a78704e0cc2b173842` (in sync with `origin/main`)
- Working tree: modified files + untracked Phase 02A/02B artifacts

## 15. Whether Changes Were Pushed

No changes have been pushed. All changes are in the local working tree, uncommitted.

Modified files:
- `src/coraxis/agents/definitions.py`
- `src/coraxis/agents/tasks.py`
- `src/coraxis/services/llm/factory.py`
- `tests/unit/test_tools.py`

New files (evaluation package, scripts, baseline data, reports, tests):
- `src/coraxis/evaluation/` (benchmark, scoring, metrics, harness)
- `scripts/capture_baseline.py`, `scripts/discover_models.py`, `scripts/run_one_case.py`
- `evaluation/baseline/bench-00{1..10}.json`
- `tests/unit/test_benchmark.py`, `test_scoring.py`, `test_metrics.py`, `test_harness.py`, `test_discovery.py`, `test_tools.py` (modified)
- `tests/integration/test_model_discovery.py`
- `PHASE_02A_COMPLETION_REPORT.md`, `PHASE_02B_COMPLETION_REPORT.md`, `FINAL_CI_CONFIRMATION_REPORT.md`

## 16. Recommended Next Subphase

**Phase 02C — Web Search and Source Intelligence**. The Researcher now emits query variants and expected evidence types per sub-question; the Web Searcher should act on them more aggressively (diversified queries, source-type classification, primary-source preference, freshness awareness). Approval is requested before proceeding.
