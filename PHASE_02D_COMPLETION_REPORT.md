# PHASE_02D_COMPLETION_REPORT — Evidence-Based Synthesis

## 1. Phase Objective

Improve the existing Synthesis Analyst so that it:

- Synthesizes findings rather than merely summarizing them.
- Grounds factual claims in available evidence.
- Connects claims to their supporting sources (traceable citations).
- Identifies conflicting or contradictory findings.
- Distinguishes established facts from uncertain conclusions.
- Identifies research gaps and insufficient evidence.
- Avoids unsupported claims and fabricated citations.
- Produces coherent, logically structured analysis.

No new agents were added. No existing features were removed. No frontend changes were made. No paid APIs were introduced.

## 2. Preconditions Verified

- Phase 02C explicitly approved and complete.
- Branch: `main`, HEAD == origin/main == `0e008a244b7f85645da0a5a78704e0cc2b173842`.
- All Phase 02A/02B/02C changes present and uncommitted.
- Phase 02C verification passed (238 tests, ruff, mypy clean).

## 3. Existing Synthesis Architecture (inspected)

| Component | File | Role |
|---|---|---|
| `Claim` / `SourceRef` / `AnalyzedFindings` | `src/coraxis/agents/tasks.py` | Analyst output schema (Pydantic, `output_json`) |
| `CitationTracker` / `Claim` / `Citation` | `src/coraxis/agents/citations.py` | Internal source/claim accumulator, stable citation numbering |
| Analyst agent definition | `src/coraxis/agents/definitions.py` | Role, goal, backstory |
| Analyst task (`analyse`) | `src/coraxis/agents/tasks.py` | CrewAI task with `output_json=AnalyzedFindings` |
| Persistence | `src/coraxis/repositories/runs.py` | `replace_claims()`, `RunClaim` model |
| DB models | `src/coraxis/db/models.py` | `RunClaim` ORM model |

## 4. Problems Identified & Fixes Implemented

### 4.1 Citation integrity (highest priority)

**Problem**: `SourceRef.citation_id` could contain fabricated IDs (e.g., `cite_999`) that don't exist in the `CitationTracker`. Nothing validated that `citation_id` values actually reference registered sources.

**Fix**:
- Added `CitationTracker.validate_citation_ids(citation_ids)` — returns the subset of IDs that actually exist in the tracker. Fabricated IDs are excluded rather than silently accepted.
- Added `Claim.model_validator` (`_enforce_evidence_strength_from_sources`) — if a claim has no supporting sources, `evidence_strength` is forced to `"insufficient"` regardless of what was set.
- Changed `Claim.evidence_strength` default from `"moderate"` to `"insufficient"` — an unsupported claim cannot claim moderate strength.
- Changed invalid `evidence_strength` fallback from `"moderate"` to `"insufficient"` — conservative when evidence is missing.

### 4.2 Persistence of new fields

**Problem**: `evidence_strength`, `limitations`, `contradicts`, and `SourceRef.citation_id` were NOT persisted. `RunClaim` model only had `claim_ref`, `text`, `confidence`, `relevance`, `agent`, `source_urls`. `claim_payload()` didn't include the new fields.

**Fix**:
- Added `evidence_strength`, `limitations`, `contradicts` columns to `RunClaim` model + Alembic migration `20261110_1536_f531e0c07457`.
- Updated `replace_claims()` to read/write the new fields.
- Updated `claim_payload()` to include them via `Claim.to_dict()` (which already includes them).
- Wired `evidence_strength`, `limitations`, `contradicts` through `RegisterClaimInput`, `RegisterClaimTool._arun()`, and `tracker.add_claim()` → `citations.py.Claim`.

### 4.3 Confidence and contradiction safety

**Problem**: An unsupported claim (no supporting sources) could default to `evidence_strength="moderate"`, which is misleading. Invalid `evidence_strength` values silently fell back to `"moderate"`.

**Fix**:
- Default `evidence_strength` changed from `"moderate"` to `"insufficient"`.
- Invalid values fall back to `"insufficient"` (not `"moderate"`).
- Model validator forces `evidence_strength="insufficient"` when `supporting_sources` is empty, regardless of what was set.
- `contradicts` and `ConflictPair` preserve both sides of a disagreement — no arbitrary resolution.

## 5. Files Changed

### `src/coraxis/agents/tasks.py`

**`SourceRef`**: Added `citation_id: str = ""` — stable citation identifier linking to the citation tracker.

**`Claim`** (output schema):
- `evidence_strength` default changed from `"moderate"` to `"insufficient"`.
- `evidence_strength` validator falls back to `"insufficient"` (not `"moderate"`) for invalid values.
- Added `model_validator` `_enforce_evidence_strength_from_sources`: if `supporting_sources` is empty, forces `evidence_strength="insufficient"`.
- Added `limitations: str`, `contradicts: list[str]`.

**`ConflictPair`** (new): `claim_a`, `claim_b`, `description`.

**`AnalyzedFindings`**: Added `conflict_pairs: list[ConflictPair]`.

**`analyse` task**: Expanded instructions — evidence strength classification with definitions, citation traceability rules (never invent citation ids, never cite unretrieved sources), mark insufficient evidence plainly, don't treat duplicate URLs as independent corroboration.

### `src/coraxis/agents/citations.py`

**`Claim`** (internal tracker model): Added `evidence_strength`, `limitations`, `contradicts` fields with `to_dict()` support.

**`CitationTracker.add_claim()`**: Accepts `evidence_strength`, `limitations`, `contradicts` parameters.

**`CitationTracker.validate_citation_ids()`** (new): Returns subset of citation_ids that exist in the tracker.

**`CitationTracker.claim_payload()`**: Now includes `evidence_strength`, `limitations`, `contradicts` via `Claim.to_dict()`.

### `src/coraxis/agents/tools/crew_tools.py`

**`RegisterClaimInput`**: Added `evidence_strength`, `limitations`, `contradicts` fields.

**`RegisterClaimTool._arun()`**: Passes new fields through to `tracker.add_claim()`.

### `src/coraxis/agents/definitions.py`

**Analyst agent definition**: Updated `goal` and `backstory` for evidence-strength classification, honest uncertainty, contradiction preservation.

### `src/coraxis/db/models.py`

**`RunClaim`**: Added `evidence_strength`, `limitations`, `contradicts` columns.

### `src/coraxis/repositories/runs.py`

**`replace_claims()`**: Now reads/writes `evidence_strength`, `limitations`, `contradicts`.

### `src/coraxis/db/migrations/versions/20261110_1536_f531e0c07457_*.py`

**New migration**: Adds `evidence_strength`, `limitations`, `contradicts` columns to `run_claims`.

### `tests/unit/test_analyst.py` (new)

22 tests covering claim-to-citation traceability, unsupported claims, citation id validation, duplicate evidence, contradiction handling, confidence categorization, research gap identification, empty evidence, missing metadata, backward compatibility, serialization round-trip.

## 6. Claim-Level Citation Design

Each `Claim` carries `supporting_sources: list[SourceRef]`, where each `SourceRef` carries a `citation_id` (the stable `cite_N` from `CitationTracker`). This creates an unbroken chain:

```
Claim.claim_id → SourceRef.citation_id → CitationTracker.citation id → Citation.url/title
```

**Citation integrity enforcement**:
- `CitationTracker.validate_citation_ids(citation_ids)` returns only IDs that exist in the tracker. Fabricated IDs are excluded.
- The analyst task instructs: every factual claim must cite at least one retrieved source via citation id; never invent citation ids; never cite unretrieved sources.
- Claims with no supporting sources are forced to `evidence_strength="insufficient"`.

## 7. Contradiction Handling

- `Claim.contradicts: list[str]` lists claim ids this claim contradicts.
- `AnalyzedFindings.conflict_pairs: list[ConflictPair]` gives structured claim pairs with descriptions.
- Existing `AnalyzedFindings.conflicts: list[str]` retained for backward compatibility.
- Analyst task instructs: preserve both sides of a disagreement, never arbitrarily select one as correct, explain when evidence cannot resolve a conflict.

## 8. Confidence Methodology

Five evidence-strength categories:

| Category | Meaning |
|---|---|
| `high` | Multiple independent, authoritative sources agree |
| `moderate` | Relevant evidence exists, but corroboration is limited |
| `low` | Weak, indirect, or incomplete evidence |
| `insufficient` | Evidence does not support a reliable conclusion |
| `conflicted` | Credible sources materially disagree |

Categories assigned by analyst LLM per claim. Numerical `confidence` (0–1) remains for granular scoring. Not presented as scientifically calibrated probabilities.

## 9. Research Gap Identification

`AnalyzedFindings.gaps` records what could not be established. Analyst task instructs to identify gaps and mark unsupported claims as `insufficient` with `limitations` explaining why.

## 10. Backward Compatibility

- `AnalyzedFindings.conflicts: list[str]` unchanged.
- `Claim.claim_id`, `text`, `supporting_sources`, `confidence`, `relevance`, `agent` unchanged.
- `SourceRef.url`, `title`, `relevance`, `snippet` unchanged; `citation_id` added with default `""`.
- `evidence_strength` defaults to `"insufficient"` (changed from `"moderate"` — more conservative).
- Invalid `evidence_strength` falls back to `"insufficient"` (changed from `"moderate"`).
- `AnalyzedFindings.conflict_pairs` defaults to `[]`.
- DB migration adds `evidence_strength`, `limitations`, `contradicts` columns to `run_claims`.
- External report contract (`FinalReport.markdown`, `executive_summary`, `key_findings`, `citations_markdown`) untouched.

## 11. Tests Added

`tests/unit/test_analyst.py` — 22 deterministic tests (no LLM, no network):

| Area | Tests |
|---|---|
| Claim-to-citation traceability | `citation_id` on `SourceRef`; unsupported claim with no sources |
| Citation identifier validation | `cite_N` format; invalid values rejected |
| Duplicate evidence | Two `SourceRef`s share one `citation_id` |
| Contradiction handling | `Claim.contradicts`; `ConflictPair`; `AnalyzedFindings.conflict_pairs` |
| Confidence categorization | All 5 `evidence_strength` values accepted; invalid falls back to `insufficient` |
| No sources → insufficient | `evidence_strength` forced to `"insufficient"` when `supporting_sources` empty |
| Research gap identification | `AnalyzedFindings.gaps` populated |
| Empty evidence | Empty `AnalyzedFindings` valid |
| Missing metadata | `Claim` with empty text valid; defaults verified |
| Backward compatibility | `SubQuestions`/`FindingItem` unchanged; `SourceRef` defaults |
| Serialization round-trip | `Claim.model_dump()` / `model_validate()` preserve all fields |

## 12. Benchmark Comparison

**Not executed.** The Phase 02A baseline (Mercury 3, all 10 cases) is preserved untouched under `evaluation/baseline/`. A Phase 02D benchmark comparison would require LLM credentials not available in this environment.

Deterministic unit tests (22 new) validate the synthesis schema behavior: traceability, contradiction handling, confidence categorization, gap identification, anti-fabrication defaults. These verify structural improvements directly without live model execution.

## 13. Known Limitations

- No end-to-end LLM execution of the analyst — structural correctness verified by tests, but real-world synthesis quality cannot be measured without live model credentials.
- Contradiction detection relies on LLM reasoning; no deterministic semantic contradiction algorithm.
- Evidence strength is assigned by the analyst LLM; code enforces structural constraints (no sources → insufficient) but doesn't cross-check against source counts.
- Source classifications remain heuristic (URL/host-based), not verified authority.

## 14. Remaining Risks

- Without live model execution, end-to-end synthesis quality cannot be quantitatively measured against Phase 02C.
- Contradiction detection quality depends on the analyst model's reasoning capability.
- Heuristic source classification may misclassify edge-case domains.

## 15. Final Git State

- Branch: `main`
- HEAD: `0e008a244b7f85645da0a5a78704e0cc2b173842` (in sync with `origin/main`)

Modified files:
- `src/coraxis/agents/definitions.py` (analyst goal/backstory)
- `src/coraxis/agents/tasks.py` (schemas + analyse task)
- `src/coraxis/agents/citations.py` (Claim fields, add_claim params, claim_payload, validate_citation_ids)
- `src/coraxis/agents/tools/crew_tools.py` (RegisterClaimInput, RegisterClaimTool._arun)
- `src/coraxis/db/models.py` (RunClaim: evidence_strength, limitations, contradicts columns)
- `src/coraxis/repositories/runs.py` (replace_claims reads/writes new fields)
- `src/coraxis/db/migrations/versions/20261110_1536_f531e0c07457_add_evidence_strength_limitations_.py` (new migration)
- `tests/unit/test_citations.py` (pre-existing, Phase 02C)

New files:
- `tests/unit/test_analyst.py` (22 new tests)

Plus all Phase 02A/02B/02C artifacts preserved unchanged.

## 16. Whether Changes Were Pushed

**No changes have been pushed.** All changes are in the local working tree, uncommitted.

## 17. Recommended Next Steps

**Phase 02E — Report Quality and Citation Reliability** is the logical next step. The Synthesis Analyst now produces structured, traceable claims with evidence strength and contradiction data; the Report Writer should consume this to produce accurate, well-cited reports with explicit limitations. Approval is requested before proceeding.