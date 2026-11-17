# Coraxis 2.0 — PHASE 02F Stage 1B
## Test Coverage Correction — Completion Report

## Executive summary

Stage 1B is a test-only stage that addresses the coverage gaps identified in
`PHASE_02F_STAGE_1A_COVERAGE_AUDIT_REPORT.md`. No V4.3 production architecture
was implemented. The existing production cancellation, exception, and cleanup
behavior in `src/coraxis/services/research.py` and
`src/coraxis/repositories/runs.py` is now pinned by deterministic unit tests,
the Groq adapter regression suite is strengthened, and a deferred contract
checklist is published for Stage 2.

Result: **30 passed, 4 strict xfailed** (the xfailed tests are the Stage 2
production-interface gatekeepers that intentionally remain unimplemented).
**Ruff: all checks passed.**

## Files changed

| File | Action | Purpose |
|------|--------|---------|
| `tests/unit/test_research_lifecycle.py` | Created | New deterministic tests for cancellation, exception, and cleanup behavior of the research orchestrator, repository, event recorder, and stop signal. |
| `tests/unit/test_groq_compatibility.py` | Modified | Added 2 Groq adapter regression tests (top-level property preservation, no base-LLM monkey patch). |
| `PHASE_02F_STAGE_1B_COMPLETION_REPORT.md` | Created | This report. |
| `PHASE_02F_DEFERRED_CONTRACT_CHECKLIST.md` | Created | Test coverage checklist for Stage 2 (items A–K). |

No production source files were modified.

## Tests added

### `tests/unit/test_research_lifecycle.py` (17 tests, all passing)

Cancellation vs ordinary exception (`ResearchOrchestrator.execute`):
1. `test_execute_cancelled_error_is_finalised_and_reraised` — `CancelledError`
   ends the run as `CANCELLED` and is re-raised (not swallowed as `Exception`).
2. `test_execute_ordinary_exception_is_finalised_and_not_reraised` — ordinary
   `Exception` ends the run as `FAILED` and does not propagate.
3. `test_execute_always_resets_contextvar_even_on_error` — `run_id_var` is
   reset in `finally` even when `_drive` errors.

Cleanup in `finally` (`ResearchOrchestrator._drive`):
4. `test_drive_cleanup_runs_when_kickoff_errors` — `watcher.cancel`,
   `fetcher.aclose`, and `recorder.stop` all run when `kickoff_async` raises.

Repository run-status behavior (real SQLite session):
5. `test_mark_finished_is_idempotent` — a late terminal write cannot clobber an
   earlier terminal state (`mark_finished` guards `is_terminal`).
6. `test_request_cancel_then_is_cancel_requested` — cancel flag is set and
   readable.
7. `test_request_cancel_on_terminal_run_returns_false` — cancelling a terminal
   run returns `False`.

`StopSignal`:
8. `test_stop_signal_starts_not_cancelled_or_timed_out`
9. `test_stop_signal_mark_cancelled`
10. `test_stop_signal_times_out`

`EventRecorder`:
11. `test_event_recorder_emit_never_raises` — `emit` suppresses `RuntimeError`
    when the loop is shutting down.
12. `test_event_recorder_stop_idempotent` — `stop` is safe to call twice.
13. `test_event_recorder_stop_after_start_cleans_up` — `stop` clears the drain task.

`_finalise` persistence handling:
14. `test_finalise_persistence_error_does_not_crash_or_publish` — persistence
    errors are swallowed; the bus is not published.
15. `test_finalise_none_run_returns_early` — a missing run is finalised without
    a crash.

`_watch_for_cancellation`:
16. `test_watch_cancellation_honours_cancel_requested` — DB cancel flag marks
    the signal.
17. `test_watch_cancellation_poll_failure_does_not_crash` — a failing poll is
    logged, not propagated.

### `tests/unit/test_groq_compatibility.py` (2 tests added, 6 passing total)

18. `test_groq_adapter_preserves_every_non_cache_breakpoint_top_level_property` —
    only the top-level `cache_breakpoint` key is removed; role, content, name,
    tool_calls, tool_call_id, and all message types (system/assistant/tool/
    function) are preserved; input is not mutated.
19. `test_groq_adapter_does_not_monkey_patch_base_llm` — the cache_breakpoint
    stripping lives only on the `GroqCompatibleLLM` subclass; CrewAI's base
    `LLM` class is untouched (no process-wide monkey patch).

## Provider-gate contract (Task 3)

The existing strict xfail test
`test_two_protocol_boundary_is_gated_to_builtin_groq_researcher`
(`tests/unit/test_two_protocol_stage1_contracts.py:128`) was **reviewed and left
unchanged**. Its assertions already distinguish:

* Built-in Groq Researcher → selector returns non-`None`.
* Non-Groq built-in Researcher → selector returns `None`.
* Custom teams → selector returns `None`.

It remains `strict=True` xfail because `build_researcher_protocols` is not
implemented. It was **not** converted into a passing test via mocks, per the
Stage 1B restriction.

## Exact commands executed

```
.\.venv\Scripts\python.exe -m pytest tests/unit/test_research_lifecycle.py tests/unit/test_groq_compatibility.py tests/unit/test_two_protocol_stage1_contracts.py -q
```

```
.\.venv\Scripts\python.exe -m pytest tests/unit/ -q
```

```
.\.venv\Scripts\python.exe -m ruff check --fix tests/unit/test_research_lifecycle.py tests/unit/test_groq_compatibility.py tests/unit/test_two_protocol_stage1_contracts.py
.\.venv\Scripts\python.exe -m ruff check tests/unit/test_research_lifecycle.py tests/unit/test_groq_compatibility.py tests/unit/test_two_protocol_stage1_contracts.py
```

## Test counts and results

| File | Passed | Failed | Xfail (strict) |
|------|--------|--------|----------------|
| `tests/unit/test_research_lifecycle.py` | 17 | 0 | 0 |
| `tests/unit/test_groq_compatibility.py` | 6 | 0 | 0 |
| `tests/unit/test_two_protocol_stage1_contracts.py` | 7 | 0 | 4 |
| **Combined** | **30** | **0** | **4** |

Broader unit suite (`tests/unit/`): **all tests pass** (including the 4 strict
xfail gatekeepers and all pre-existing tests), no regressions.

Ruff: **all checks passed** (1 import-sort fix auto-applied, 0 remaining).

## Failures, skips and limitations

* **No failures.** All 30 executed tests pass; 4 strict xfails are expected
  (Stage 2 production interfaces not yet implemented).
* **Limitations (documented, not fixed in Stage 1B):**
  * Items E, F, G, K from the deferred checklist (`RunCoordination`,
    `ActionLease`, exactly-once release, preparation ownership) cannot be tested
    until those production types exist (V4.3 §13 step 2).
  * Items H and I (event persistence/publication failure) are exercised by
    existing production code (`EventRecorder._flush` swallows persistence errors)
    but have no dedicated deterministic test yet; deferred to Stage 2.
  * Items J (cancellation/timeout races → `unknown` terminal status) and the
    two-protocol provider/protocol/context boundaries (A–D) are strict xfails
    awaiting Stage 2 implementation.
* Two harmless `RuntimeWarning`s about coroutines never awaited appear in the
  output; they originate from `unittest.mock` patching async functions and do
  not indicate test defects.

## Restrictions respected

* Test-only changes — no production source modified.
* No `RunCoordination`, `ActionLease`, or two-protocol orchestration implemented.
* No dependency manifests, migrations, API contracts, or `SubQuestions` schema
  changed.
* No baseline/evaluation data changed.
* No live API calls or benchmarks run.
* No commit, push, reset, clean, stash, discard, or deletion performed.
* No existing backups or uncommitted work overwritten.
* All pre-existing uncommitted modifications preserved.

## Uncommitted changes before and after execution

**Before:** 16 modified files (`pyproject.toml`, `requirements.txt`,
`src/coraxis/agents/citations.py`, `src/coraxis/agents/crew.py`,
`src/coraxis/agents/definitions.py`, `src/coraxis/agents/tasks.py`,
`src/coraxis/agents/tools/crew_tools.py`, `src/coraxis/agents/tools/fetch.py`,
`src/coraxis/db/models.py`, `src/coraxis/repositories/runs.py`,
`src/coraxis/services/llm/__init__.py`, `src/coraxis/services/llm/factory.py`,
`src/coraxis/services/research.py`, `tests/unit/test_citations.py`,
`tests/unit/test_report_parsing.py`, `tests/unit/test_tools.py`) plus ~26
untracked files (reports, plans, `CONTEXT.md`, new source/tests).

**After:** identical set of pre-existing modifications, plus the 4 new/modified
files listed above under "Files changed." No pre-existing change was touched,
removed, or overwritten.

## Stop condition

Stage 1B complete. Report generated. Deferred contract checklist published at
`PHASE_02F_DEFERRED_CONTRACT_CHECKLIST.md`.

**STOPPED.** Do not begin Stage 2 without explicit user approval.
