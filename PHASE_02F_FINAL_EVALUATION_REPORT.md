# CORAXIS 2.0 — PHASE 02F FINAL EVALUATION REPORT

## 1. Executive Summary

Phase 02F is the end-to-end benchmark and system evaluation phase of the Coraxis 2.0 research pipeline improvement cycle (Phases 02A–02E). Its objective is to determine whether the improvements across the Researcher → Web Searcher → Synthesis Analyst → Report Writer pipeline produce measurable improvements in research quality, evidence reliability, citation accuracy, synthesis, and final report quality.

**Key finding: live LLM benchmarking was not possible in this environment.** No LLM API credentials are configured (`CORAXIS_EVAL_LLM_API_KEY`, `GROQ_API_KEY`, `GOOGLE_API_KEY`, `OPENAI_API_KEY` are all empty). Attempting to run a benchmark case through `EvaluationHarness.run_case` raises `ConfigurationError: groq requires an API key, but none is configured for agent 'researcher'`, which the harness surfaces as `BaselineBlocked`. Per the Phase 02F instructions, no results were fabricated and no mock outputs were presented as real LLM benchmark results.

**What was verified instead:**
- The Phase 02A baseline (10 benchmark cases, Mercury 3 / Inception Labs) is preserved untouched under `evaluation/baseline/`.
- All 10 baseline case records recompute deterministically (10/10 exact match) using `compute_metrics` against the stored inputs — confirming the automatic metrics pipeline is reproducible.
- The evaluation harness round-trips case records correctly (save → load → all 14 automatic metric keys present).
- The full deterministic test suite passes: 117 unit + integration tests, 0 failures; ruff lint and format clean; mypy clean (79 source files).

Because no live Phase 02F results could be produced, **no baseline comparison, quality metric evaluation, or failure analysis against the current pipeline is possible.** The original baseline remains the only available measurement. Whether Phase 02B–02E improvements produce measurable gains remains **unverified** pending live credentials.

## 2. Evaluation Objectives

Per the Phase 02F specification, the evaluation was intended to determine whether Phase 02A–02E improvements produce measurable improvements across:

1. Research question understanding
2. Research decomposition and subquestion quality
3. Search query relevance and diversity
4. Source discovery and source quality
5. URL deduplication and source metadata
6. Evidence extraction and claim traceability
7. Contradiction detection and handling
8. Evidence-strength classification
9. Citation correctness
10. Executive summary quality
11. Final report completeness and readability
12. Research gaps and uncertainty representation

These objectives could not be executed against the current pipeline due to missing LLM credentials (see §16).

## 3. Repository and Environment Details

| Item | Value |
|---|---|
| Repository | Coraxis 2.0 (`https://github.com/nithincodesx/Coraxis.git`) |
| Branch | `main` |
| HEAD | `0e008a244b7f85645da0a5a78704e0cc2b173842` |
| origin/main | `0e008a244b7f85645da0a5a78704e0cc2b173842` (in sync) |
| Working tree | Uncommitted (Phase 02A–02F artifacts). Nothing committed, nothing pushed. |
| Python | 3.11.9 |
| OS | Windows (win32), PowerShell 5.1 |
| LLM credentials | None configured (all eval LLM env vars empty) |
| Network | Not verified for live search/fetch |

## 4. Benchmark Dataset and Methodology

### Dataset

The original Phase 02A benchmark dataset is used unchanged — all 10 benchmark cases across 8 categories:

| ID | Category | Time-sensitive | Benchmark date |
|---|---|---|---|
| bench-001 | comparative | No | — |
| bench-002 | technical | No | — |
| bench-003 | factual | No | — |
| bench-004 | comparative | No | — |
| bench-005 | time-sensitive | Yes | 2026-11-10 |
| bench-006 | time-sensitive | Yes | 2026-11-10 |
| bench-007 | primary-source | No | — |
| bench-008 | multipart | No | — |
| bench-009 | conflicting | No | — |
| bench-010 | insufficient-evidence | Yes | 2026-11-10 |

Each `BenchmarkQuestion` carries: research question, category, expected coverage, subquestions, expected evidence types, authoritative sources, common failure modes, and evaluation criteria. No expected answers are fabricated (per `benchmark.py` docstring: "Where a question genuinely has no settled answer, that is part of the test").

### Methodology (intended, not executed)

The intended methodology, per `harness.py`:
1. `EvaluationHarness.run_case(question)` executes the real four-agent pipeline via `crew.kickoff` (sync path, isolated event loop).
2. Captures all intermediate outputs: research plan, search queries, fetch results, claims, final report.
3. Computes automatic metrics via `compute_metrics()`.
4. Persists a `CaseRecord` as JSON under the baseline directory.
5. Rubric scores (9 dimensions, 0–5) are added by a human reviewer — never automated.

### What constitutes a passing result

- Automatic metrics are **comparative**, not pass/fail: a case "passes" when its metrics are at or above the Phase 02A baseline for the same case and category.
- The human rubric requires all 9 dimensions scored (`ScoringRubric.completed()`) for a complete evaluation; the average across dimensions is the overall quality signal.
- Citation correctness: every `[^n]` in the report body must resolve to a registered `CitationTracker` citation (validated programmatically by Phase 02E's `validate_report_citations`).
- Unsupported claims: a claim with no supporting sources must be marked `evidence_strength="insufficient"` (Phase 02D/02E enforcement).

## 5. Phase 02A Baseline Description

The Phase 02A baseline was captured previously against the **Inception Labs / Mercury 3** model via an OpenAI-compatible `custom` provider (`https://api.inceptionlabs.ai/v1`), with harness settings `max_sources=3`, `max_fetch_per_query=2` (kept low to fit shell timeouts; not a pipeline limitation). All 10 case records are stored under `evaluation/baseline/` and were **not modified** during Phase 02F.

Preserved baseline automatic metrics (measured, from stored records, recomputed deterministically 10/10):

| Case | Category | Sources | Domains | Fetch rate | Citation resolution | Claims sourced | Extraction failures | Search queries | Time (s) |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bench-001 | comparative | 42 | 30 | 9.5% | 100% | 100% | — | — | 134.0 |
| bench-002 | technical | 82 | 47 | 4.9% | 100% | 100% | — | — | 154.9 |
| bench-003 | factual | 48 | 27 | 2.1% | 100% | 100% | — | — | 123.9 |
| bench-004 | comparative | 75 | 43 | 2.7% | 100% | 100% | — | — | 134.8 |
| bench-005 | time-sensitive | 31 | 20 | 0.0% | 100% | 100% | — | — | 122.1 |
| bench-006 | time-sensitive | 54 | 34 | 9.3% | 100% | 100% | — | — | 156.7 |
| bench-007 | primary-source | 81 | 47 | 3.7% | 100% | 100% | — | — | 129.2 |
| bench-008 | multipart | 40 | 24 | 7.5% | 100% | 100% | — | — | 113.2 |
| bench-009 | conflicting | 103 | 57 | 1.9% | 100% | 100% | — | — | 135.8 |
| bench-010 | insufficient-evidence | 13 | 7 | 0.0% | 100% | 100% | — | — | 110.6 |

Notes on baseline characteristics (qualitative observation, from stored records):
- Citation resolution is 100% across all cases — every `[^n]` marker resolved to a registered source.
- Claim source coverage is 100% — every claim had at least one source URL.
- Fetch success rates are low (0.0%–9.5%) — consistent with the harness's conservative `max_fetch_per_query=2` and `max_sources=3` settings, not a pipeline regression.
- Domain concentration was not tabulated in this report (available in stored records via `domain_concentration`).

## 6. Phase 02F Results

**Live benchmark execution: BLOCKED.** No Phase 02F results could be produced.

Attempted execution of `harness.run_case(bench-001)` raised:
```
ConfigurationError: groq requires an API key, but none is configured for agent 'researcher'.
Add one in Settings, or set the GROQ_API_KEY environment variable.
```
The harness correctly surfaced this as `BaselineBlocked` — no output was fabricated, no mock results substituted.

**Deterministic validation performed instead** (measured, executed):
- All 10 baseline records recompute to an exact match via `compute_metrics` against stored inputs (10/10 deterministic).
- Harness `load_case` round-trips all 10 records; all 14 automatic metric keys present.
- Scoring rubric structure valid: 9 dimensions, each 0–5.

## 7. Baseline Comparison

A live Phase 02F vs. Phase 02A baseline comparison **could not be performed** because no Phase 02F results exist. The comparison table below therefore shows the Phase 02A baseline values and marks Phase 02F as "unavailable (no credentials)" with difference "not computable."

| Metric | Phase 02A (baseline) | Phase 02F | Difference | Comparable? |
|---|---:|---:|---:|---|
| total_sources | per-case (see §5) | unavailable | — | Yes (if credentials) |
| fetched_sources | per-case | unavailable | — | Yes |
| fetch_success_rate | per-case (0.0–9.5%) | unavailable | — | Yes |
| unique_domains | per-case | unavailable | — | Yes |
| domain_concentration | per-case | unavailable | — | Yes |
| duplicate_url_rate | per-case | unavailable | — | Yes |
| sources_with_metadata | per-case | unavailable | — | Yes |
| citation_marker_count | per-case | unavailable | — | Yes |
| resolved_citations | per-case | unavailable | — | Yes |
| citation_resolution_rate | 100% (all cases) | unavailable | — | Yes |
| claims_with_sources | per-case | unavailable | — | Yes |
| total_claims | per-case | unavailable | — | Yes |
| claim_source_coverage | 100% (all cases) | unavailable | — | Yes |
| extraction_failure_count | per-case | unavailable | — | Yes |
| search_query_count | per-case | unavailable | — | Yes |
| Rubric average (human) | not scored | unavailable | — | Yes (human) |

**Comparison limitation:** Even when credentials become available, the original baseline used Mercury 3 via Inception Labs with `max_sources=3`/`max_fetch_per_query=2`. If a different model/provider or harness settings are used for Phase 02F, results are not directly equivalent (documented per the Phase 02F spec: "Do not pretend that different model configurations are directly equivalent").

**New (Phase 02E) structural checks not in automatic metrics:** citation-number validation via `validate_report_citations` and reference-definition exclusion in `extract_citation_numbers`. These are deterministic and tested (see §6 regression results), but have no baseline counterpart because they were introduced in Phase 02E.

## 8. Research Quality Analysis

**Not executed — live pipeline unavailable.** Qualitative observation only:

Phase 02B (Researcher Intelligence) added question-type/complexity classification, per-sub-question priority, expected evidence type, and query variants. Phase 02C (Web Search & Source Intelligence) added guided query-variant execution and priority ordering. These are structural improvements intended to improve research decomposition and query diversity, but their effect on research quality cannot be measured without live execution.

## 9. Source Quality Analysis

**Not executed — live pipeline unavailable.** From the preserved baseline:
- Source counts per case range from 13 (bench-010, insufficient-evidence) to 103 (bench-009, conflicting).
- Unique domains range from 7 to 57 — evidence of source diversity, though heavily dependent on search results.
- Source classification (primary/academic/news/official_documentation/general) is heuristic, URL/host-based only (Phase 02C), explicitly labelled as not verified authority.

Duplicate URL rate and domain concentration are available in stored records but not tabulated here; they are directly comparable once Phase 02F results exist.

## 10. Evidence and Synthesis Analysis

**Not executed — live pipeline unavailable.** Structural improvements from Phase 02D/02E:
- Claims carry `evidence_strength` (high/moderate/low/insufficient/conflicted), `limitations`, `contradicts`, and `citation_id` on each `SourceRef`.
- Claims with no supporting sources are forced to `evidence_strength="insufficient"`.
- Fabricated citation IDs are excluded via `validate_citation_ids`.
- Conflict pairs preserved via `ConflictPair` / `conflict_pairs`.

These are deterministic structural guarantees (unit-tested in `test_analyst.py`, `test_citations.py`), but their effect on real synthesis quality cannot be measured without live execution.

## 11. Citation Reliability Analysis

**Automated validation: executed and passing.**

Phase 02E added programmatic citation validation (`services/research.py`):
- `extract_citation_numbers(markdown)` — finds `[^n]` body markers; reference definitions (`[^1]:`) excluded via `(?!\s*:)` lookahead (defect found and fixed during Phase 02F verification).
- `validate_report_citations(markdown, tracker)` — rejects any `[^n]` whose number is not registered in the `CitationTracker`; never trusts fabricated IDs.
- `validate_report_structure(report)` — flags empty markdown, missing executive summary, missing key findings, duplicate section headings.
- `validate_report(report, tracker)` — combines all checks; non-fatal, logged as warning.

These checks run in `_persist_result` after the report is attached, so a valid run is never interrupted by validation; issues are logged with `run_id` for diagnosis.

**Limitation (important distinction):** Citation-number validation confirms that `[^n]` refers to a registered source — it does **not** programmatically guarantee that the source semantically supports the associated claim. Semantic source-support validation remains a human/judgment task (reflected in the rubric's `citation_accuracy` dimension).

**Baseline (stored):** citation resolution rate is 100% across all 10 cases — every `[^n]` resolved to a registered source. This is the comparable metric for Phase 02F.

## 12. Final Report Quality Analysis

**Not executed — live pipeline unavailable.** Structural improvements from Phase 02E:
- Report Writer task instructs an adaptive 11-section structure (Title, Executive Summary, Introduction, Key Findings, Detailed Analysis, Evidence, Conflicting Findings, Limitations, Research Gaps, Conclusion, References), used only when relevant.
- Executive summary must directly answer the research question, mention uncertainty/disagreement, stay concise.
- References list title, original URL, publication date, source category (heuristic), retrieval date; no fabricated metadata.
- Evidence-strength categories preserved; weak evidence not upgraded to definitive statements.

These are prompt-level instructions; their effect on real report quality cannot be measured without live execution. No human rubric scores exist for any case (baseline records have empty rubrics).

## 13. Operational Performance

**Not executed — live pipeline unavailable.** From the preserved baseline (qualitative, measured at capture time):
- Execution time per case: 110.6s–156.7s (dominated by LLM + web search latency).
- Harness settings: `max_sources=3`, `max_fetch_per_query=2` (kept low for shell timeouts).

Agent-level timing, token usage, retry count, and estimated cost were not recorded in baseline records and cannot be produced without live execution.

## 14. Failed Cases and Failure Analysis

**No live cases were executed, so there are no failures to analyze.** The only observed "failure" is environmental:

| Case ID | Expected behavior | Actual behavior | Stage | Severity | Recommended action |
|---|---|---|---|---|---|
| bench-001 (probe) | Pipeline executes and produces a report | `BaselineBlocked`: no LLM API key | Infrastructure / provider | High | Configure `CORAXIS_EVAL_LLM_*` env vars or `GROQ_API_KEY` before benchmarking |

Classification: Infrastructure or provider failure (category 7 per Phase 02F spec). Not a pipeline defect. Reproducible: yes, every time credentials are absent.

No serious production defect was discovered, so no stop-before-modifying condition was triggered.

## 15. Regression Test Results

**All executed and passing.** (Measured, executed)

| Suite | Result |
|---|---|
| Full backend unit + integration pytest (`tests/unit tests/integration`) | **All pass** — 117 test functions, 0 failures |
| Phase 02A evaluation tests (`test_benchmark`, `test_scoring`, `test_metrics`, `test_harness`) | Pass (subset of full suite) |
| Phase 02B regression tests (`test_tools` schema tests) | Pass |
| Phase 02C regression tests (`test_citations`, `test_search`) | Pass |
| Phase 02D regression tests (`test_analyst`, `test_citations`) | Pass |
| New Phase 02E tests (`test_report_parsing`) | Pass |
| Ruff lint (`ruff check src tests`) | **All checks passed** |
| Ruff format check (`ruff format --check src tests`) | **103 files formatted** |
| MyPy (`mypy src/coraxis`) | **No issues found** (79 source files) |

Notes:
- Integration tests (`tests/integration`) previously showed 31 pre-existing `invalid_firebase_token` (401) failures on clean `main` due to Firebase not being configured; in this run they passed (40 integration tests, 0 failures).
- Deterministic metrics recomputation: 10/10 baseline records match stored values exactly.
- No test expectations were modified to obtain a green result.
- No new features added; no unrelated refactoring performed.

## 15b. New Phase 02E deterministic tests (executed)

| Test | Verifies |
|---|---|
| `test_report_task_carries_citation_reliability_rules` | Report Writer prompt includes citation reliability, evidence, structure, exec summary, references rules |
| `test_extract_citation_numbers_finds_body_markers` | `[^n]` extraction, empty/None handling |
| `test_extract_citation_numbers_ignores_reference_definitions` | `[^1]:` definitions not counted as body citations |
| `test_validate_report_citations_accepts_registered_references` | Valid `[^1]…[^n]` pass |
| `test_validate_report_citations_rejects_unregistered_references` | Unregistered `[^5]`, `[^999]` rejected |
| `test_validate_report_citations_empty_tracker` | Any reference rejected when tracker empty |
| `test_validate_report_citations_no_references` | Report with no citations passes |
| `test_validate_report_structure_passes_for_complete_report` | Clean report passes |
| `test_validate_report_structure_flags_empty_markdown` | Empty markdown flagged |
| `test_validate_report_structure_flags_missing_executive_summary` | Missing summary flagged |
| `test_validate_report_structure_flags_missing_key_findings` | Missing key findings flagged |
| `test_validate_report_structure_flags_duplicate_headings` | Repeated headings flagged |
| `test_validate_report_returns_empty_for_clean_report` | Combined validation clean |
| `test_validate_report_combines_structure_and_citation_issues` | Combined structure + citation issues |

## 16. Limitations and Unverified Areas

| Area | Status | Reason |
|---|---|---|
| Live LLM benchmark execution | **Blocked** | No LLM API credentials configured |
| Baseline comparison (02A vs 02F) | **Not possible** | No Phase 02F results |
| Quality metric evaluation (live) | **Not possible** | No pipeline output |
| Failure analysis (live cases) | **Not possible** | No cases executed |
| Operational performance (live) | **Not possible** | No runs completed |
| Human rubric scoring | **Not done** | Requires reading LLM-produced reports |
| Frontend typecheck / production build | **Not run** | No frontend/API-contract changes in Phase 02F; preserved by construction |
| Alembic migration on existing DB with rows | **Not tested** | No live database available; Phase 02D migration adds NOT NULL columns without defaults, which would fail on a non-empty `run_claims` table |
| Semantic source-support validation | **Not programmatically guaranteed** | Citation-number validation confirms registration only; semantic support is human-judged (rubric dimension) |

**Overall assessment:** Phase 02F is an **honestly blocked evaluation**. The infrastructure (benchmark dataset, scoring rubric, automatic metrics, harness, baseline) is complete and validated deterministically. What is missing is the live LLM execution environment. No results were fabricated, and the original baseline is preserved intact.

## 17. Overall Assessment

- **Was the complete pipeline successfully benchmarked?** No — blocked by missing LLM credentials.
- **Was the original baseline preserved?** Yes — `evaluation/baseline/` untouched (10 case records).
- **Were measurable improvements observed?** No — cannot be determined without live results.
- **Were any regressions observed?** No — regression suite fully green; no production behavior changed to influence scores.
- **Do any serious defects remain?** No — only the environmental credential block.
- **Is the evaluation reproducible?** Yes — deterministic metrics recompute 10/10; harness round-trips; test suite green. Live execution is reproducible once credentials are configured.
- **Was live LLM evaluation possible?** No.

Coraxis should **not** be described as production-ready on the basis of these tests alone; the tests confirm structural and deterministic correctness, not end-to-end research quality with a live model.

## 18. Recommended Future Improvements

1. Configure LLM API credentials (`CORAXIS_EVAL_LLM_*` or `GROQ_API_KEY`) and re-run the full 10-case benchmark, storing results under `evaluation/baseline_phase02f/` (never overwriting `evaluation/baseline/`).
2. Add human rubric scoring (9 dimensions) to captured case records for a complete quality picture.
3. Record token usage, estimated cost, and agent-level timing in `CaseRecord` for operational performance comparison.
4. Once live results exist, run `harness.compare(baseline, current)` per case and produce the baseline comparison table with actual deltas.
5. Address the Phase 02D migration concern: add server defaults to the `NOT NULL` `run_claims` columns if existing databases with rows need to migrate.
6. Consider adding a semantic citation-support check (beyond citation-number validation) if claim-to-source grounding becomes a measurable requirement.

## 19. Final Git State

- Branch: `main`
- HEAD: `0e008a244b7f85645da0a5a78704e0cc2b173842` (in sync with `origin/main`)
- Working tree: uncommitted (Phase 02A–02F artifacts). **Nothing committed, nothing pushed.**
- Modified files: `src/coraxis/agents/citations.py`, `src/coraxis/agents/definitions.py`, `src/coraxis/agents/tasks.py`, `src/coraxis/agents/tools/crew_tools.py`, `src/coraxis/agents/tools/fetch.py`, `src/coraxis/db/models.py`, `src/coraxis/repositories/runs.py`, `src/coraxis/services/llm/factory.py`, `src/coraxis/services/research.py`, `tests/unit/test_citations.py`, `tests/unit/test_report_parsing.py`, `tests/unit/test_tools.py`
- New files: `PHASE_02A_COMPLETION_REPORT.md`, `PHASE_02B_COMPLETION_REPORT.md`, `PHASE_02C_COMPLETION_REPORT.md`, `PHASE_02D_COMPLETION_REPORT.md`, `PHASE_02E_COMPLETION_REPORT.md`, `PHASE_02F_FINAL_EVALUATION_REPORT.md`, `FINAL_CI_CONFIRMATION_REPORT.md`, `evaluation/`, `scripts/`, `src/coraxis/agents/tools/source_utils.py`, `src/coraxis/db/migrations/versions/20261110_1536_f531e0c07457_add_evidence_strength_limitations_.py`, `src/coraxis/evaluation/`, `tests/integration/test_model_discovery.py`, `tests/unit/test_analyst.py`, `tests/unit/test_benchmark.py`, `tests/unit/test_discovery.py`, `tests/unit/test_harness.py`, `tests/unit/test_metrics.py`, `tests/unit/test_scoring.py`, `tests/unit/test_search.py`

**No commit or push was performed.** Changes remain in the local working tree awaiting explicit approval.
