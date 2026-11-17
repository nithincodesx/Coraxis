# Coraxis 2.0 — PHASE 02F STAGE 1A
## Test Coverage Gap Investigation — Audit Report

## Executive summary

Stage 1 completed its stated verification: 13 passed, 4 strict xfailed, ruff clean. However, as an audit of the original Stage 1 requirements in the recovery plan, coverage is **partial at best**. The existing tests cover the Groq adapter regression and contract preservation well, but **none of the six Stage 1 requirement categories are fully satisfied** by tests that exist today.

The four strict xfail tests are correctly structured as gatekeepers for Stage 2 production interfaces, but they assert absence (the interfaces do not exist), not presence of behavior. They verify the gap, not a contract.

The sections the plan requires — exception handling, cancellation handling, lease cleanup, event persistence/publication failure — have **zero corresponding tests**. No test in either file references `except`, `BaseException`, `cancel`, `cleanup`, `lease`, `release`, `finally`, or event persistence/publication failure.

**Final recommendation: PASS WITH GAPS.**

---

## 1. Requirement-by-requirement coverage matrix

| # | Requirement category | Covered? | Evidence / gap |
|---|---------------------|----------|----------------|
| 1 | Provider-gate tests | PARTIAL | Tests distinguish Groq vs non-Groq vs custom at the **adapter** level (factory returns GroqCompatibleLLM vs LLM). No test references a future two-protocol selector or protocol split. The interface under test is the existing Groq adapter, not the two-protocol architecture. |
| 2 | Protocol A contract tests | GAP | Exists only as strict xfail asserting `build_protocol_a_task` is unimplemented. No positive contract test exists. |
| 3 | Protocol B contract tests | GAP | Exists only as strict xfail asserting `build_protocol_b_formatter_task` is unimplemented. No positive contract test exists. |
| 4 | Downstream context tests | GAP | Exists only as strict xfail asserting `tasks[1].context == [tasks[0]]` etc. No passing test verifies the context behavior today. |
| 5 | Existing adapter regression tests | COVERED | 4 tests in `test_groq_compatibility.py` pass: deep-copy, cache_breakpoint removal only, metadata/tool preservation, non-Groq/build-path separation. |
| 6 | Exception and cleanup safeguards | GAP | Zero tests exist for ordinary Exception, cancellation handling, BaseException avoidance, or lease cleanup after persistence/publication failure. |

---

## 2. Exact test names and file locations

### `tests/unit/test_two_protocol_stage1_contracts.py`

| Test name | Line | Result | What it actually verifies |
|-----------|------|--------|---------------------------|
| `test_non_groq_builtin_pipeline_retains_existing_structured_contract` | 69 | passed | `build_pipeline_tasks` returns 4 tasks; task[0].output_json is `SubQuestions`. Existing structured-output contract preserved. |
| `test_custom_team_retains_existing_sequential_team_behavior` | 76 | passed | `build_team_crew` with one custom spec returns 1 task with role "Custom One" and `output_json is None`. Custom-team path unchanged. |
| `test_non_groq_providers_do_not_select_groq_adapter` | 101 | passed (parametrized: openai, gemini, ollama, custom) | `build_llm` does not return `GroqCompatibleLLM` for non-groq providers. Adapter selection preserved. |
| `test_builtin_groq_llm_uses_existing_instance_local_adapter` | 113 | passed | `build_llm` returns `GroqCompatibleLLM` for provider="groq". Existing adapter selected. |
| `test_two_protocol_boundary_is_gated_to_builtin_groq_researcher` | 128 | xfail (strict) | Asserts `crew.build_researcher_protocols` exists and returns non-None only for builtin Groq researcher. **Verifies the interface is missing**, not behavior. |
| `test_protocol_a_uses_native_tools_without_structured_output` | 148 | xfail (strict) | Asserts `crew.build_protocol_a_task` exists, returns task with `output_json is None`, `output_pydantic is None`, and native tools. **Verifies the interface is missing**, not behavior. |
| `test_protocol_b_uses_no_tools_and_subquestions_output_json` | 172 | xfail (strict) | Asserts `crew.build_protocol_b_formatter_task` exists, returns task with `tools == []` and `output_json is SubQuestions`. **Verifies the interface is missing**, not behavior. |
| `test_downstream_tasks_use_only_explicit_immediate_predecessor_context` | 188 | xfail (strict) | Asserts `tasks[1].context == [tasks[0]]` etc. **Verifies immediate-predecessor context is not wired today**, not that it works correctly when implemented. |
| `test_existing_pipeline_contract_remains_observable_before_split` | 196 | passed | Records baseline: 4 tasks, roles in order, all `output_json is not None`. Baseline observation only. |
| `test_contract_fixture_payload_is_not_secret_bearing` | 209 | passed | Fixture configs contain no `api_key` secret material. Hygiene test only. |

### `tests/unit/test_groq_compatibility.py`

| Test name | Line | Result | What it actually verifies |
|-----------|------|--------|---------------------------|
| `test_groq_adapter_removes_only_cache_breakpoint_without_mutation` | 39 | passed | `_prepare_completion_params` deep-copies, removes top-level `cache_breakpoint` only, preserves metadata/role/tool_calls, does not mutate input. |
| `test_groq_adapter_handles_multiple_messages_and_nested_metadata` | 60 | passed | Nested `cache_breakpoint` in content/metadata is preserved; only top-level key removed. |
| `test_non_groq_build_path_returns_standard_llm` | 79 | passed | `build_llm` for openai returns standard `LLM`, not `GroqCompatibleLLM`. |
| `test_groq_build_path_returns_instance_local_adapter` | 93 | passed | `build_llm` for groq returns `GroqCompatibleLLM`. |

---

## 3. Investigation findings

### Investigation 1: Exception handling

| Sub-requirement | Status | Finding |
|-----------------|--------|---------|
| Ordinary Exception handling | NOT COVERED | No test references `except`, `Exception`, or error handling paths. |
| Explicit cancellation handling | NOT COVERED | No test references cancellation. Production cancellation exists in `services/research.py` and `repositories/runs.py` but is untested by Stage 1. |
| Cancellation propagation without swallowing | NOT COVERED | No test. |
| Avoiding broad `BaseException` catches as ordinary failures | NOT COVERED | No test. Note: `factory.py:210` uses `except Exception as exc:  # noqa: BLE001` in `validate_provider_key` — this is production code, not tested by Stage 1. |
| Cleanup after an exception | NOT COVERED | No test references `finally`, `cleanup`, or exception-path cleanup. |

**Result: 0 of 5 exception-handling requirements have tests.**

### Investigation 2: Lease cleanup

| Sub-requirement | Status | Finding |
|-----------------|--------|---------|
| Event persistence failure | NOT COVERED | No test references event persistence, SSE, or `EventRecorder` failure. |
| Event publication failure | NOT COVERED | No test references event publication failure. |
| Duplicate release attempts | NOT COVERED | No test references `release_once`, `ActionLease`, or duplicate release. `RunCoordination` / `ActionLease` do not exist in source (confirmed by grep — zero matches in `src/`). |
| Exactly-once release semantics | NOT COVERED | Same as above — production types not implemented; no tests exist. |
| Cleanup after cancellation | NOT COVERED | No test. |
| Cleanup after an ordinary exception | NOT COVERED | No test. |

**Result: 0 of 6 lease-cleanup requirements have tests.** The production types these tests would exercise (`RunCoordination`, `ActionLease`) are confirmed absent from `src/`.

### Investigation 3: Provider gate

- **Built-in Groq Researcher:** `test_builtin_groq_llm_uses_existing_instance_local_adapter` verifies `build_llm` returns `GroqCompatibleLLM` for provider="groq". This tests the **existing adapter**, not a two-protocol boundary.
- **Non-Groq built-in Researcher:** `test_non_groq_providers_do_not_select_groq_adapter` (parametrized) verifies non-groq providers do not return `GroqCompatibleLLM`. Again, adapter-level, not protocol-level.
- **Custom agent teams:** `test_custom_team_retains_existing_sequential_team_behavior` verifies `build_team_crew` returns a single task with no structured output. Custom-team path preserved.

**Key distinction:** These tests verify selection of the **existing Groq compatibility adapter** via `build_llm`. They do **not** verify selection of a future two-protocol architecture. The only test touching the future architecture is the strict xfail `test_two_protocol_boundary_is_gated_to_builtin_groq_researcher`, which asserts `build_researcher_protocols` does not exist yet — it verifies the gap, not a contract.

### Investigation 4: Protocol boundaries (four strict xfail tests)

| Test | Has meaningful assertion? | Failure cause | Could pass incorrectly? | Strict? | Independent context test? |
|------|--------------------------|---------------|------------------------|---------|---------------------------|
| `test_two_protocol_boundary_is_gated_to_builtin_groq_researcher` | Yes — asserts selector existence + return values | `build_researcher_protocols` attribute missing → `getattr` returns None → first assert fails | No — would fail if selector exists but returns wrong values too | strict=True | N/A |
| `test_protocol_a_uses_native_tools_without_structured_output` | Yes — asserts builder existence + task attributes | `build_protocol_a_task` attribute missing → first assert fails | No — asserts multiple attributes that would fail independently | strict=True | N/A |
| `test_protocol_b_uses_no_tools_and_subquestions_output_json` | Yes — asserts builder existence + task attributes | `build_protocol_b_formatter_task` attribute missing → first assert fails | No | strict=True | N/A |
| `test_downstream_tasks_use_only_explicit_immediate_predecessor_context` | Yes — asserts context lists | `build_pipeline_crew` does not wire `context` → assertion on `tasks[1].context` fails | Low — could pass if `context` happens to equal lists, but current code doesn't set it | strict=True | **Yes** — tests downstream contexts independently, but only as an expected failure |

All four xfail markers are `strict=True`, so if Stage 2 implements the interfaces incorrectly (e.g., wrong return values), the tests will still fail — they are genuine gatekeepers, not placeholders that could pass trivially.

### Investigation 5: Test quality

**Weaknesses found:**

1. **No tests for requirement category 6 (exception/cleanup).** The plan explicitly lists ordinary exceptions, cancellation, BaseException avoidance, and guaranteed lease cleanup. None exist.

2. **No positive Protocol A / Protocol B / context tests.** All three are xfail-only. There is no passing test that would validate a correct Stage 2 implementation — only tests that fail until implementation exists.

3. **Provider-gate tests assert adapter selection, not protocol selection.** The requirement says "Built-in Groq Researcher selects the new two-protocol path." The tests assert `build_llm` returns `GroqCompatibleLLM`. These are different things.

4. **Mock/fixture-only verification.** `test_contract_fixture_payload_is_not-secret_bearing` and `test_existing_pipeline_contract_remains_observable_before_split` are hygiene/baseline observations, not behavioral contracts.

5. **Accidental coupling risk.** The context test uses `build_pipeline_crew(_specs(), _context())` — if `_specs` or `_context` change, the test breaks for reasons unrelated to context wiring. This is mild coupling but acceptable for a contract test.

**False-positive risk:** Low. All xfail are strict. Passing tests are specific assertions.

**False-negative risk:** High. The suite cannot detect a Stage 2 implementation that builds the interfaces but gets the semantics wrong (e.g., wrong tool set, wrong context order) — there are no positive tests to catch regressions once Stage 2 lands.

---

## 4. False-positive and false-negative risks

| Risk | Likelihood | Impact | Mitigation status |
|------|-----------|--------|-------------------|
| False positive: xfail passes incorrectly | Low | Medium | Strict xfail prevents this. |
| False negative: Stage 2 implements wrong semantics, suite still green | High | High | No positive Protocol A/B/context tests exist to catch semantic errors. |
| False negative: Exception/cleanup bugs undetected | High | High | Zero tests for these categories. |
| False positive: Adapter test passes but protocol selection wrong | Medium | Medium | Tests assert adapter, not protocol. |

---

## 5. Recommended additional deterministic tests

These should be added **after** Stage 2 production interfaces exist (they are listed here as recommendations, not implemented, per audit-only scope):

**Protocol A (after `build_protocol_a_task` exists):**
- `test_protocol_a_task_has_native_tools_and_no_structured_output` — positive version of the xfail, asserting specific tool set and `output_json is None`.
- `test_protocol_a_task_does_not_delegate` — `allow_delegation is False`.

**Protocol B (after `build_protocol_b_formatter_task` exists):**
- `test_protocol_b_formatter_has_no_tools_and_subquestions_output` — positive version.
- `test_protocol_b_output_validates_against_subquestions_schema` — instantiate `SubQuestions` from formatter output.

**Downstream context (after context wiring exists):**
- `test_downstream_context_is_strict_immediate_predecessor` — positive version, plus assert `tasks[0].context == []` (no predecessor for first task).

**Provider gate (after `build_researcher_protocols` exists):**
- `test_two_protocol_selector_returns_protocols_for_builtin_groq_researcher` — positive version.
- `test_two_protocol_selector_returns_none_for_non_groq_and_custom` — positive version.

**Exception and cleanup (require production `RunCoordination` / `ActionLease`):**
- `test_lease_cleanup_after_event_persistence_failure` — simulate persistence error, assert lease released exactly once.
- `test_lease_cleanup_after_event_publication_failure` — simulate publication error, assert lease released exactly once.
- `test_duplicate_release_is_noop` — call release twice, assert `in_flight_actions` decremented once.
- `test_cancellation_not_swallowed_as_ordinary_failure` — cancellation propagates distinctly from `Exception`.
- `test_broad_baseexception_not_used_for_ordinary_failures` — inspect source or behavior to confirm `BaseException` is not caught as ordinary failure.
- `test_cleanup_after_ordinary_exception` — exception during action, assert lease cleanup runs.

**Adapter regression (additional):**
- `test_groq_adapter_preserves_all_non_cache_breakpoint_keys` — iterate all keys, assert only `cache_breakpoint` removed.
- `test_groq_adapter_handles_non_dict_messages_gracefully` — non-dict message entries pass through unchanged.

---

## 6. Verification scope

Commands executed:

```
.\.venv\Scripts\python.exe -m pytest tests/unit/test_two_protocol_stage1_contracts.py tests/unit/test_groq_compatibility.py -q
```
Result: **13 passed, 4 xfailed** in 41.80s.

```
.\.venv\Scripts\python.exe -m ruff check tests/unit/test_two_protocol_stage1_contracts.py
```
Result: **All checks passed.**

```
.\.venv\Scripts\python.exe -m pytest tests/unit/ --ignore=tests/unit/test_two_protocol_stage1_contracts.py --ignore=tests/unit/test_groq_compatibility.py -q
```
Result: **all remaining unit tests passed** (no failures reported across the broader suite).

**Sufficiency assessment:** These commands confirm Stage 1's own verification targets were met (13 passed, 4 expected failures, lint clean). They do **not** provide sufficient evidence that the original Stage 1 requirements in the recovery plan are fully satisfied — specifically the exception handling and lease cleanup categories have no tests at all, and the protocol/context/provider-gate requirements are verified only by expected-failure stubs.

Additional deterministic commands that should be run once Stage 2 interfaces exist:
```
.\.venv\Scripts\python.exe -m pytest tests/unit/test_two_protocol_stage1_contracts.py -q
```
(positive versions replacing the xfail stubs)
Plus the new exception/cleanup tests listed above.

---

## 7. Repository preservation confirmation

**Audit performed: read-only.** No source files, tests, manifests, migrations, reports, or backups were modified, deleted, overwritten, or discarded.

Uncommitted changes before and after audit: **identical.**

Modified files (16): pyproject.toml, requirements.txt, src/coraxis/agents/citations.py, src/coraxis/agents/crew.py, src/coraxis/agents/definitions.py, src/coraxis/agents/tasks.py, src/coraxis/agents/tools/crew_tools.py, src/coraxis/agents/tools/fetch.py, src/coraxis/db/models.py, src/coraxis/repositories/runs.py, src/coraxis/services/llm/__init__.py, src/coraxis/services/llm/factory.py, src/coraxis/services/research.py, tests/unit/test_citations.py, tests/unit/test_report_parsing.py, tests/unit/test_tools.py.

Untracked files preserved: CONTEXT.md, all CORAXIS_*.md plans/reports, evaluation/, scripts/, src/coraxis/agents/context_injector.py, src/coraxis/agents/tools/source_utils.py, db migrations, src/coraxis/evaluation/, src/coraxis/services/llm/groq_compat.py, all tests/unit/*.py files.

One new file created by this audit: `PHASE_02F_STAGE_1A_COVERAGE_AUDIT_REPORT.md` (this deliverable only).

---

## 8. Final recommendation

**PASS WITH GAPS.**

Stage 1's own verification (13 passed, 4 strict xfailed, ruff clean) is sound. However, against the original recovery-plan requirements, coverage is incomplete:

- **Covered:** Groq adapter regression, provider adapter selection, custom-team preservation, existing pipeline contract baseline, fixture hygiene.
- **Not covered:** ordinary Exception handling, cancellation handling, cancellation propagation, BaseException avoidance, cleanup after exception, event persistence failure, event publication failure, duplicate release, exactly-once release, cleanup after cancellation — zero tests exist for any of these.
- **Stub-only (no positive coverage):** Protocol A boundary, Protocol B boundary, downstream context, two-protocol provider gate.

**Do not proceed to Stage 2** until these gaps are addressed or explicitly accepted. No fixes or implementation were performed in this audit.
