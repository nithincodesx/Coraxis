# Coraxis 2.0 — PHASE 02F Stage 1B
## Deferred Test Coverage Checklist

This checklist records the two-protocol Researcher contracts that Stage 1
intentionally defers to Stage 2. None of these are implemented or tested yet;
they are tracked here so Stage 2 can convert each from a strict xfail (or
absence) into a passing deterministic test.

Source: `CORAXIS_RESEARCHER_TWO_PROTOCOL_IMPLEMENTATION_PLAN_V4.3.md`, section 13
("Implementation sequence and expected files").

## Implementation sequence (from V4.3 §13)

1. Contract and provider-gate tests.                              [Stage 1 — done]
2. RunCoordination, pre-operation ledger registration, preparation
   ownership, atomic terminalization, release, memory-first enforcement. [Stage 2]
3. Coordination-aware channel freeze, deep detached snapshot, digest.      [Stage 2]
4. Protocol A raw native-tool builder.                                        [Stage 2]
5. Protocol B no-tools formatter and explicit predecessor contexts.           [Stage 2]
6. Orchestrator integration, retries, cancellation, events, statistics.       [Stage 2]
7. Existing Groq adapter regression tests.                                    [Stage 1 — done]
8. Isolated diagnostics, then one controlled four-agent live run.             [Stage 2]

## Checklist

| ID | Contract | Becomes a passing test in | V4.3 §13 step | Status in Stage 1 |
|----|----------|---------------------------|---------------|-------------------|
| A | Protocol A — native tools, no structured output | Stage 2 | step 4 | Strict xfail (`build_protocol_a_task` missing) |
| B | Protocol B — no tools, `output_json=SubQuestions` | Stage 2 | step 5 | Strict xfail (`build_protocol_b_formatter_task` missing) |
| C | Immediate-predecessor task contexts | Stage 2 | step 5/6 | Strict xfail (`tasks[N].context == [tasks[N-1]]`) |
| D | Groq-only protocol selection (built-in researcher gate) | Stage 2 | step 2 | Strict xfail (`build_researcher_protocols` missing) |
| E | RunCoordination — lock, leases, seq, accepting_actions/mutations | Stage 2 | step 2 | Not implemented; no test |
| F | ActionLease — preparation ownership, terminalization, release | Stage 2 | step 2 | Not implemented; no test |
| G | Exactly-once release (duplicate release is a no-op) | Stage 2 | step 2 | Not implemented; no test |
| H | Event persistence failure — swallowed, no broadcast | Stage 2 | step 6 | Not tested (production `EventRecorder._flush` already swallows) |
| I | Event publication failure — does not corrupt terminal state | Stage 2 | step 6 | Not tested |
| J | Cancellation and timeout races — `unknown` terminal status blocks retry | Stage 2 | step 6 | Not tested |
| K | Preparation ownership — worker cannot sanitize after timeout owns `unknown` | Stage 2 | step 2 | Not implemented; no test |

## Notes

* Items E, F, G, K depend on the `RunCoordination` / `ActionLease` types, which do
  not exist in production source yet. They cannot be meaningfully tested until
  V4.3 §13 step 2 is implemented.
* Items H and I are partially exercised by existing production code
  (`EventRecorder._flush` catches `Exception` and returns without broadcasting),
  but there are no deterministic tests for them yet.
* Item J overlaps with existing cancellation behavior in
  `src/coraxis/services/research.py` (`execute` distinguishes `CancelledError`
  from `Exception`), but the two-protocol `unknown`-terminal-status race is not
  covered until Stage 2.
* All items must remain unimplemented during Stage 1. Do not convert strict
  xfail tests into passing tests via mocks that assume intended behavior.
