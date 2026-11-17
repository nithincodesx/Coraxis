# Coraxis 2.0 — PHASE 02F RECOVERY
## STAGE 1: DETERMINISTIC CONTRACT TESTS ONLY — Completion Report

## Scope

Stage 1 is strictly for test coverage and contract verification of the approved
V4.3 two-protocol Researcher architecture. No production orchestration,
RunCoordination, ActionLease, or two-protocol production code was implemented.

## Verification Executed

Command 1 (deterministic contract tests):

```
.\.venv\Scripts\python.exe -m pytest tests/unit/test_two_protocol_stage1_contracts.py tests/unit/test_groq_compatibility.py -q
```

Command 2 (lint):

```
.\.venv\Scripts\python.exe -m ruff check tests/unit/test_two_protocol_stage1_contracts.py
```

## Test Counts and Results

- **13 passed**
- **4 xfailed** (strict expected failures — Stage 2 boundaries not yet implemented)
- Ruff: **all checks passed**

### Expected failures (strict xfail, Stage 2 must implement)

1. `test_two_protocol_boundary_is_gated_to_builtin_groq_researcher` — `build_researcher_protocols` selector not implemented.
2. `test_protocol_a_uses_native_tools_without_structured_output` — `build_protocol_a_task` builder not implemented.
3. `test_protocol_b_uses_no_tools_and_subquestions_output_json` — `build_protocol_b_formatter_task` builder not implemented.
4. `test_downstream_tasks_use_only_explicit_immediate_predecessor_context` — explicit predecessor contexts not wired.

## Coverage Verified

### Provider-gate tests
- Built-in Groq Researcher selects Groq adapter (`test_builtin_groq_llm_uses_existing_instance_local_adapter`).
- Non-Groq providers (openai, gemini, ollama, custom) do not select Groq adapter (`test_non_groq_providers_do_not_select_groq_adapter`).
- Custom teams retain existing sequential behavior (`test_custom_team_retains_existing_sequential_team_behavior`).
- Non-Groq built-in pipeline retains existing structured-output contract (`test_non_groq_builtin_pipeline_retains_existing_structured_contract`).

### Protocol A contract tests
- Strict xfail: native tools without structured output boundary (`build_protocol_a_task`).

### Protocol B contract tests
- Strict xfail: no-tools formatter with `output_json=SubQuestions` boundary (`build_protocol_b_formatter_task`).

### Downstream context tests
- Strict xfail: immediate-predecessor context wiring.

### Existing adapter regression tests
- Groq compatibility adapter behavior preserved (`tests/unit/test_groq_compatibility.py`, 4 passed).

### Exception and cleanup safeguards
- Contract fixture payload verified secret-free (`test_contract_fixture_payload_is_not_secret_bearing`).
- Existing pipeline contract observable before split (`test_existing_pipeline_contract_remains_observable_before_split`).

## Files Changed (this session)

No source files were modified during this verification session. Tests and lint were read-only operations.

## Uncommitted Changes Detected

### Before execution
Modified: pyproject.toml, requirements.txt, src/coraxis/agents/citations.py, src/coraxis/agents/crew.py, src/coraxis/agents/definitions.py, src/coraxis/agents/tasks.py, src/coraxis/agents/tools/crew_tools.py, src/coraxis/agents/tools/fetch.py, src/coraxis/db/models.py, src/coraxis/repositories/runs.py, src/coraxis/services/llm/__init__.py, src/coraxis/services/llm/factory.py, src/coraxis/services/research.py, tests/unit/test_citations.py, tests/unit/test_report_parsing.py, tests/unit/test_tools.py

Untracked: CONTEXT.md, CORAXIS_*.md plans/reports, evaluation/, scripts/, src/coraxis/agents/context_injector.py, src/coraxis/agents/tools/source_utils.py, db migrations, src/coraxis/evaluation/, src/coraxis/services/llm/groq_compat.py, various tests/unit/* files

### After execution
Identical to before — no new modifications introduced.

## Restrictions Respected

- No RunCoordination implemented.
- No ActionLease or action ledger implemented.
- No two-protocol production orchestration implemented.
- No dependency manifests modified.
- No database migrations modified.
- No external API contracts changed.
- SubQuestions schema not modified.
- No evaluation/baseline modified.
- No existing reports or evaluation outputs modified.
- No live API calls made.
- No benchmarks run.
- No commit or push performed.
- No reset, clean, stash, discard, or delete performed.
- No existing backups or uncommitted work overwritten.

All pre-existing modifications and recovery assets preserved.

## Stop Condition

Stage 1 complete. Report generated at `PHASE_02F_STAGE_1_COMPLETION_REPORT.md`.

**STOPPED.** Do not proceed to Stage 2 without explicit user approval.
