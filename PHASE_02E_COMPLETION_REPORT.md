# PHASE 02E COMPLETION REPORT — Report Quality & Citation Reliability

## 1. Initial Git state

- Branch: `main`
- HEAD: `0e008a244b7f85645da0a5a78704e0cc2b173842` (docs: add PHASE_01_5_VERIFICATION_REPORT.md)
- origin/main: `0e008a244b7f85645da0a5a78704e0cc2b173842` (in sync)
- Working tree: contains uncommitted Phase 02A–02D changes (preserved, untouched) plus Phase 02E changes below.
- Phase 02D final verification: complete — 238 tests passed, ruff lint/format clean, mypy clean. Approved as precondition for Phase 02E.
- No changes committed or pushed. All work sits in the local working tree.

## 2. Existing Report Writer architecture (inspected)

| Component | File | Role |
|---|---|---|
| Report Writer agent definition | `src/coraxis/agents/definitions.py:78` | `summarizer` slug; goal/backstory for polished markdown reports |
| Report output schema | `src/coraxis/agents/tasks.py:281` | `FinalReport`: `markdown`, `executive_summary`, `key_findings`, `citations_markdown`, `stats` |
| Report Writer task | `src/coraxis/agents/tasks.py:383` | CrewAI task, `output_json=FinalReport`, bound to summarizer agent |
| Crew assembly | `src/coraxis/agents/crew.py` | `build_pipeline_crew`: sequential researcher → web_searcher → analyst → summarizer |
| Report parsing | `src/coraxis/services/research.py:696` | `_parse_report`: coerces CrewAI result into `FinalReport`, graceful raw-markdown fallback |
| Report persistence | `src/coraxis/services/research.py:569` | `_persist_result`: saves markdown, summary, key findings, citations, stats via `run_repo` |
| Citation tracker | `src/coraxis/agents/citations.py` | `CitationTracker`: `cite_N` → stable `number` → `[^n]`; `validate_citation_ids()` |
| API report download | `src/coraxis/api/v1/endpoints/runs.py:118` | `GET /runs/{id}/report.md` returns `run.report_markdown` |
| Frontend consumer | `frontend/src/components/ReportPanel.tsx` | Renders `report_markdown` as preformatted text; `claims` tab uses `source_urls` |

## 3. Problems identified

1. **Thin Report Writer prompt** — the `report` task only specified a 5-section skeleton and generic formatting rules. It gave no guidance on citation reliability, evidence-strength representation, conflict handling, uncertainty, or adaptive structure.
2. **No programmatic citation validation** — nothing verified that `[^n]` markers in the report body referred to sources actually registered in the `CitationTracker`. A fabricated citation (`cite_9999`) could reach the final report undetected.
3. **No structural validation** — empty reports, missing executive summaries, missing key findings, and duplicated section headings were not detected.
4. **Evidence strength not connected to report instructions** — Phase 02D gave the Analyst `evidence_strength`, `limitations`, `contradicts`, and `conflict_pairs`, but the Report Writer was never told to preserve them or avoid upgrading weak evidence.

## 4. Files changed (Phase 02E only)

Modified:
- `src/coraxis/agents/tasks.py` — rewrote the `report` Task description (citation reliability, evidence handling, report structure, executive summary, references, readability).
- `src/coraxis/services/research.py` — added `extract_citation_numbers`, `validate_report_citations`, `validate_report_structure`, `validate_report`; wired `validate_report` into `_persist_result` (non-fatal, logged).
- `tests/unit/test_report_parsing.py` — added 18 deterministic tests for the Report Writer task wiring, citation extraction, citation validation, structural validation, and combined validation.

Preserved unchanged (pre-existing Phase 02A–02D work): all other modified and untracked files, including `citations.py`, `definitions.py`, `crew_tools.py`, `fetch.py`, `db/models.py`, `repositories/runs.py`, `services/llm/factory.py`, `test_citations.py`, `test_tools.py`, the `evaluation/` package, `scripts/`, baseline data, and the phase reports.

No database migrations added. No API schemas changed. No frontend files changed.

## 5. Report structure improvements

The Report Writer task now instructs an adaptive 11-section structure, used only when relevant:

1. Title
2. Executive Summary
3. Introduction and Research Scope
4. Key Findings
5. Detailed Analysis
6. Evidence and Supporting Sources
7. Conflicting Findings
8. Limitations and Uncertainties
9. Research Gaps
10. Conclusion
11. References

Rules enforced in the prompt:
- Do not force irrelevant sections; maintain logical progression; meaningful headings; focused paragraphs.
- Do not repeat the executive summary in the introduction.
- Avoid excessive headings and unnecessarily long reports.
- Use tables/lists where they aid comprehension.

## 6. Citation validation design

Added deterministic, non-fatal validation in `src/coraxis/services/research.py`:

- `extract_citation_numbers(markdown)` — finds `[^n]` body markers (reference definitions `[^1]:` excluded).
- `validate_report_citations(markdown, tracker)` — rejects any `[^n]` whose number is not registered in the `CitationTracker` (the single source of truth for `cite_N` numbering). Never trusts fabricated IDs.
- `validate_report_structure(report)` — flags empty markdown, missing executive summary, missing key findings, and duplicated section headings.
- `validate_report(report, tracker)` — combines all checks; returns descriptive issue strings, never fails a run.

Wiring:
- `_persist_result` calls `validate_report(report, tracker)` after attaching the report and logs issues as a warning (or debug on success). Validation is non-fatal: a run still succeeds even if the LLM produced citation issues, matching the "handle malformed LLM output gracefully" requirement. No bounded retry loop is added (avoids unnecessary model calls / infinite retries); the existing `_parse_report` graceful fallback remains.

The `FinalReport` schema fields are unchanged (`markdown`, `executive_summary`, `key_findings`, `citations_markdown`, `stats`), preserving the API and frontend contract. `citations_markdown` continues to default to `tracker.format_markdown()` when the LLM omits it.

## 7. Claim-to-report traceability

- The Report Writer task prompt explicitly states it receives the Analyst's claims as context: each claim carries supporting sources (citation ids, URLs, titles, relevance), evidence strength, limitations, contradictions, plus research gaps and overall confidence.
- The prompt mandates: every factual claim carries an inline `[^n]` matching a source in the Analyst's findings; citations refer only to actually-retrieved sources; never invent citation ids, URLs, titles, authors, or dates; never cite a source that does not support the claim; place citations close to claims; preserve citation numbering; no citation dumps over unrelated claims.
- Internal identifiers (`claim_id`, `citation_id`) are used only in the prompt instructions to the LLM and in programmatic validation; they are not exposed in the user-facing report beyond the stable `[^n]` convention already in use.
- A report statement that cannot be reliably linked to evidence is instructed to be stated as insufficient rather than as an established fact.

## 8. Evidence and uncertainty handling

The Report Writer prompt preserves the Analyst's evidence-strength categories (high / moderate / low / insufficient / conflicted) and instructs:
- Do not upgrade weak evidence into definitive statements.
- Represent conflicting findings fairly; explain when evidence cannot resolve a disagreement.
- Distinguish an unanswered research question from a negative finding.
- Preserve claim limitations; do not override the evidence assessment.
- Where evidence is insufficient, state that plainly instead of manufacturing a citation.
- Do not invent numerical confidence scores or claim scientific calibration.

The Report Writer does not override the Analyst's evidence assessment to produce a more confident-sounding report.

## 9. Reference generation improvements

Prompt rules:
- List every cited source once: title, original URL, publication date (if known), source category (labelled heuristic), retrieval date.
- Do not fabricate missing bibliographic metadata; handle unavailable titles/dates gracefully.
- Ensure all cited references are included; do not list uncited sources (no separate uncited bibliography).
- Do not present heuristic source categories as verified authority rankings.

The authoritative `citations_markdown` appendix is produced by `tracker.format_markdown()` (already emits `[^n]: **title** — <url>` with relevance bars and snippets), which is used when the LLM leaves it empty.

## 10. Output validation

Deterministic checks (in `services/research.py`, non-fatal, logged):
- Empty report content → flagged.
- Missing executive summary → flagged.
- Invalid citation references (`[^n]` not registered) → flagged.
- Missing reference entries → addressed by defaulting `citations_markdown` to `tracker.format_markdown()` when empty.
- Duplicate references → duplicate section headings flagged; tracker dedups sources by normalized URL so reference entries are not duplicated.
- Malformed Markdown → `_parse_report` gracefully falls back to raw markdown.
- Empty/malformed sections → structural validation flags missing executive summary / key findings.
- Missing required output fields → `FinalReport` Pydantic schema handles defaults.
- Unsupported claims where detectable → citation validation catches unregistered `[^n]` references; the prompt forbids fabricated citations.

Malformed LLM output is handled gracefully by the existing `_parse_report` fallback; no infinite retries or unbounded model calls are introduced.

## 11. Backward compatibility

- `FinalReport` fields unchanged: `markdown`, `executive_summary`, `key_findings`, `citations_markdown`, `stats`.
- `ReportStats` schema unchanged; orchestrator continues to overwrite `stats` from `tracker.stats()`.
- `ClaimOut`/API schemas unchanged (Phase 02D's `evidence_strength`/`limitations`/`contradicts` remain DB-persisted but not API-exposed, as before Phase 02E).
- Frontend `ReportPanel.tsx` and `types.ts` unchanged; `report_markdown` contract preserved.
- Previously persisted reports unaffected (no migration, no schema change, no data transformation).
- No database migrations added.

## 12. Tests and exact results

New tests in `tests/unit/test_report_parsing.py` (18 added), all deterministic (no LLM, no network, no credentials):

| Test | What it verifies |
|---|---|
| `test_report_task_carries_citation_reliability_rules` | Report Writer task prompt includes citation reliability, evidence, structure, exec summary, references rules |
| `test_extract_citation_numbers_finds_body_markers` | `[^n]` extraction, empty/None handling |
| `test_extract_citation_numbers_ignores_reference_definitions` | `[^1]:` definitions not double-counted |
| `test_validate_report_citations_accepts_registered_references` | Valid `[^1]…[^n]` pass |
| `test_validate_report_citations_rejects_unregistered_references` | Unregistered `[^5]`, `[^999]` rejected; registered not flagged |
| `test_validate_report_citations_empty_tracker` | Any reference rejected when tracker empty |
| `test_validate_report_citations_no_references` | Report with no citations passes |
| `test_validate_report_structure_passes_for_complete_report` | Clean report passes |
| `test_validate_report_structure_flags_empty_markdown` | Empty markdown flagged |
| `test_validate_report_structure_flags_missing_executive_summary` | Missing summary flagged |
| `test_validate_report_structure_flags_missing_key_findings` | Missing key findings flagged |
| `test_validate_report_structure_flags_duplicate_headings` | Repeated headings flagged |
| `test_validate_report_returns_empty_for_clean_report` | Combined validation clean |
| `test_validate_report_combines_structure_and_citation_issues` | Combined reports structure + citation issues |

Exact verification commands and results, executed in the repository root:

| Command | Result |
|---|---|
| `python -m pytest tests/unit` | **All pass** |
| `python -m pytest tests/integration` | **All pass** (40 tests; no Firebase/env failures in this environment) |
| `python -m pytest tests/unit tests/integration` | **All pass** — 0 failures |
| `ruff check src tests` | **All checks passed** |
| `ruff format --check src tests` | **103 files formatted** |
| `mypy src/coraxis` | **No issues found** (79 source files) |

No test was reported as passing unless executed. All commands above were executed and passed.

### Defect found and resolved during verification

`extract_citation_numbers` initially used `r"\[\^(\d+)\]"`, which counted reference definitions (`[^1]: ...`) as body citations. Fixed to `r"\[\^(\d+)\](?!\s*:)"` so reference definitions are excluded; test updated accordingly. This was a precision correction: the previous regex never caused false rejections (it only ever marked a registered citation as "referenced"), but it was technically inaccurate per the requirement.

### Reported (but not executable here) suites

- Phase 02A/B/C/D regression tests are subsets of the unit suite above and pass as part of it.
- Frontend typecheck/production build: **not run** — Phase 02E makes no frontend or API-schema changes; the `FinalReport`/`RunDetail` contract and `report_markdown` field are unchanged, so frontend compatibility is preserved by construction.
- Alembic migration test against a live database: **not executed** (no database available in this environment). See the migration limitation in §14.

## 13. Benchmark comparison or limitations

The Phase 02A baseline (`evaluation/baseline/`, Mercury 3, all 10 cases) is preserved untouched. No Phase 02E baseline re-run was executed because no LLM API credentials are available in this environment (same blocker documented in Phases 02C–02D). Deterministic unit tests validate the structural improvements directly; real-world report quality (citation coverage, unsupported-claim frequency, executive-summary relevance) remains unverified without live model execution.

If credentials become available, compare against `evaluation/baseline/` and store new results separately under `evaluation/baseline_phase02e/` per the Phase 02E spec, evaluating: report completeness, citation correctness, citation coverage, unsupported-claim frequency, executive-summary relevance, structural consistency, readability, repetition, and evidence/limitation preservation.

## 14. Known limitations

- No end-to-end LLM execution of the Report Writer; structural correctness is verified by tests, but real-world report quality cannot be measured without live model credentials.
- Citation validation is non-fatal and logged only; it does not auto-repair the LLM's markdown body (programmatic rewriting of LLM prose was deemed too risky). The authoritative `citations_markdown` appendix is always regenerated from the tracker when empty.
- Evidence-strength representation depends on the Analyst LLM populating `evidence_strength`/`limitations`/`contradicts`; code enforces structural constraints (no sources → insufficient) but does not cross-check strength against source counts.
- Source classifications remain heuristic (URL/host-based), not verified authority.
- DNS rebinding TOCTOU and other SSRF residual risks from Phase 02C are unchanged and unaffected by Phase 02E.
- Frontend compatibility preserved by construction; not empirically exercised via a production build.
- Database migration (Phase 02D, pre-existing — not introduced by 02E): migration `f531e0c07457` adds three `NOT NULL` columns (`evidence_strength`, `limitations`, `contradicts`) to `run_claims` without server defaults. It applies cleanly on a fresh/empty `run_claims` table but would fail on an existing database that already has rows (PostgreSQL and SQLite-with-rows both reject adding NOT NULL columns without defaults). Could not be tested without a live database. Phase 02E adds no migrations of its own.

## 15. Final Git state

- Branch: `main`
- HEAD: `0e008a244b7f85645da0a5a78704e0cc2b173842` (in sync with `origin/main`)
- Working tree: uncommitted (Phase 02A–02E). Nothing committed, nothing pushed.
- Modified files (Phase 02E additions shown with pre-existing Phase 02A–02D changes preserved):
  - `src/coraxis/agents/tasks.py` (Phase 02B schemas + Phase 02E report task)
  - `src/coraxis/services/research.py` (Phase 02E validation + wiring)
  - `tests/unit/test_report_parsing.py` (Phase 02E tests)
  - Plus pre-existing Phase 02A–02D modified files: `citations.py`, `definitions.py`, `crew_tools.py`, `fetch.py`, `db/models.py`, `repositories/runs.py`, `services/llm/factory.py`, `test_citations.py`, `test_tools.py`
- New files: `PHASE_02E_COMPLETION_REPORT.md`; all Phase 02A–02D artifacts (`evaluation/`, `scripts/`, baseline data, phase reports, new tests) preserved unchanged.

## 16. Recommended next phase

Per the Phase 02D report, Phase 02E completes the 02A–02E improvement cycle. No Phase 02F is planned or started here. Wait for explicit approval before any further work. Changes are **not** committed or pushed.
