# Coraxis Researcher Two-Protocol Implementation Plan V4.1

## 1. Scope and preserved architecture

This is a planning-only clarification of
[`CORAXIS_RESEARCHER_TWO_PROTOCOL_IMPLEMENTATION_PLAN_V4.md`](C:/Users/shulk/OneDrive/Desktop/Researcher/CORAXIS_RESEARCHER_TWO_PROTOCOL_IMPLEMENTATION_PLAN_V4.md).
It does not authorize implementation and does not modify application source,
tests, dependencies, migrations, reports, baselines, evaluation outputs, or
external contracts.

The approved architecture remains unchanged:

- two Coraxis-controlled CrewAI kickoffs;
- Groq-only built-in Researcher rollout;
- unchanged non-Groq and custom-team behavior;
- Protocol A with native tools and no structured output;
- Protocol B as a no-tools formatter using `output_json=SubQuestions`;
- explicit immediate-predecessor task contexts;
- per-attempt memory-first enforcement;
- run-wide side-effect retry protection;
- a redacted, immutable, run-local handoff capped at 65,536 UTF-8 bytes;
- the existing Groq cache-marker adapter;
- no dependency changes or database migrations.

V4.1 resolves two implementation inconsistencies:

1. side-effect admission, mutation, and freeze now have one coherent ordering;
2. read-only timeout has separate terminal-status ownership and lease-release
   ownership, so late workers cannot double-finalize or produce a successful
   handoff while still running.

The ledger provides exactly-once **lease finalization within the live process**,
not exactly-once tool execution. A process crash can lose the in-memory ledger;
the old run must then fail conservatively or require a new user-created run.

## 2. Current code boundary

[`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py)
owns the per-run `ToolContext` passed into agent-specific views.

[`src/coraxis/agents/comms.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/comms.py)
owns the run-local message and blackboard state. Its existing separate
`transcript()` and `entries()` calls are not sufficient for a handoff; the
two-protocol path requires one coordination-aware atomic snapshot.

[`src/coraxis/agents/tools/crew_tools.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tools/crew_tools.py)
contains the six relevant tools. `send_message` and `blackboard_write` mutate
the channel; the other Researcher tools are read-only for retry purposes.

## 3. Single run-level coordination object

Create one `RunCoordination` per run and inject the same object into
`ToolResultCollector`, `ToolContext`, and `AgentChannel`:

```python
RunCoordination:
    lock: threading.RLock
    changed: threading.Condition(lock)
    accepting_actions: bool
    accepting_mutations: bool
    freeze_requested: bool
    frozen: bool
    in_flight_actions: int
    leases: dict[int, ActionLease]
    next_seq: int
    next_attempt: int
    cancellation_requested: bool
    deadline: float | None
```

This is the sole synchronization authority for the two-protocol path.
Collector and channel coordinated state must not acquire independent locks.
If legacy private locks remain for unrelated callers, the coordinated path
must never call them while holding another object lock.

The only allowed order is:

```text
RunCoordination.lock
  -> collector state
  -> channel state
```

No path acquires a collector or channel lock first, and no path acquires
channel state and then collector state. The freeze path, tool wrappers,
`send_message`, and `blackboard_write` all enter through the coordination
lock. Consequently, no reverse lock ordering is possible in the coordinated
implementation.

## 4. Single-owner action lease model

### 4.1 Lease states

Each accepted action has one lease with two independent pieces of state:

```python
ActionLease:
    seq: int
    attempt: int
    tool: ToolName
    side_effect: bool
    phase: Literal["admitted", "running", "released"]
    terminal_status: Literal["started", "succeeded", "failed", "unknown"]
    terminal_owner: str | None
    release_owner: str | None
    started_at: float
    finished_at: float | None
```

The ledger also stores sanitized input/result summaries and error categories.
`seq` is monotonic within the run; `(attempt, seq)` identifies the action in
diagnostics.

There are two once-only transitions:

1. **Terminalization:** `started -> succeeded|failed|unknown`, owned by the
   first caller that wins under `coordination.lock`.
2. **Lease release:** `running/admitted -> released`, owned by the worker
   completion path, timeout-detachment path, or freeze failure path that first
   removes the lease.

The same owner may perform both transitions, but they are not conflated.
`in_flight_actions` is decremented only by the single release owner. A late
worker cannot decrement it a second time.

### 4.2 Terminal transition rule

`finalize_once(seq, status, result_or_error, owner)` executes under
`coordination.lock`:

```text
if lease.terminal_status != "started":
    return ALREADY_FINALIZED
lease.terminal_status = status
lease.terminal_owner = owner
lease.finished_at = now
store sanitized result/error
notify changed
return WON
```

The first terminal transition wins. A late success cannot overwrite unknown;
a duplicate failure cannot overwrite success. If sanitization or ledger
storage fails after the operation has run, the owner finalizes `unknown` with
`result_recording_failed` when possible. The action is unsafe for retry.

### 4.3 Release rule

`release_once(seq, owner)` executes under `coordination.lock`:

```text
if lease.phase == "released":
    return ALREADY_RELEASED
lease.phase = "released"
coordination.leases.pop(seq)
coordination.in_flight_actions -= 1
coordination.changed.notify_all()
return WON
```

An action may be terminalized as unknown while its worker remains alive, but
its lease is not released until the worker has stopped or the implementation
has a safe detached-owner acknowledgement. Therefore, `in_flight_actions`
continues to represent live workers that could still return.

## 5. Coherent side-effect strategy

### 5.1 Two-phase side-effect lease

Side-effecting local operations use a two-phase protocol:

1. **Admission phase:** under `coordination.lock`, check policy, memory-first
   ordering, cancellation, and freeze state; reserve the sequence, record
   `started`, create an `admitted` lease, and increment in-flight count.
2. **Mutation gate:** reacquire `coordination.lock` immediately before the
   local channel mutation. If freeze has begun, finalize the lease as
   `failed` with `mutation_rejected_after_freeze`, release it, and do not
   mutate. If freeze has not begun, change phase to `running` and perform the
   bounded local mutation while still holding the coordination lock.
3. **Completion:** finalize success/failure/unknown, release the lease, and
   notify the condition.

The operation does not mutate while merely admitted. This removes the
impossible V4 state in which an action is both holding the lock and waiting
for mutation permission.

Only the short, local `AgentChannel` mutation is performed while holding the
coordination lock. No network request, provider call, filesystem operation, or
unbounded work may hold it.

### 5.2 Freeze ordering proof

Freeze acquires the same `coordination.lock`:

1. If a side-effect action acquires the lock first at its mutation gate, it
   changes to `running`, mutates, finalizes, releases, and only then can freeze
   acquire the lock. The mutation is included in the snapshot.
2. If freeze acquires the lock first, it sets
   `freeze_requested=True`, `accepting_actions=False`, and
   `accepting_mutations=False`. A later mutation gate sees the closed state,
   finalizes the admitted action as a pre-operation rejection, releases it,
   and never mutates the channel.
3. No side-effecting mutation can occur between channel freeze and snapshot,
   because both mutation and snapshot require the same lock and the mutation
   gate rejects after freeze.

Thus freeze never snapshots during a collaboration mutation, and no accepted
action can mutate after the freeze boundary. An accepted side-effect action
that loses the gate before execution is finalized as a known rejection, not
as an unresolved external side effect. Any action that has entered mutation
execution but cannot establish its outcome is `unknown` and blocks retry.

### 5.3 Side-effect timeout policy

The local mutation phase is bounded and non-blocking by design. If an
unexpected timeout/exception occurs after mutation begins, terminalize as
`unknown` unless the mutation outcome is definitively known, release once, and
fail Protocol A conservatively. Never retry automatically.

If a future side-effect implementation includes external I/O, that I/O must
run outside the coordination lock after admission. The subsequent local
mutation gate must recheck freeze state. An interrupted external operation is
always `unknown` for retry purposes, even if the local mutation never begins.

## 6. Read-only action strategy

### 6.1 Normal read-only execution

For `web_search`, `recall_memory`, `read_inbox`, and `blackboard_read`:

1. Acquire `coordination.lock`.
2. Validate cancellation, action acceptance, freeze state, and memory-first.
3. Reserve sequence, record `started`, create a `running` lease, increment
   in-flight count.
4. Release the lock.
5. Execute the operation outside the lock.
6. Reacquire the lock and call `finalize_once`.
7. Release the lease once and return the normal result.

No read-only external/network operation holds the coordination lock.

### 6.2 Read-only timeout while worker continues

A timeout controller may win the terminal transition with `unknown`, but it
must not release the lease while the worker can still return:

1. Under `coordination.lock`, set cancellation and stop new admissions.
2. Call `finalize_once(seq, unknown, "read_timeout", "timeout-controller")`.
3. Keep the lease and `in_flight_actions` count.
4. Signal cancellation to the worker where supported.
5. Wait for worker completion until the run deadline/grace period.
6. If the worker exits, its completion path calls `release_once`; late result
   finalization is a no-op.
7. If the worker does not exit, fail the run and do not build a successful
   handoff. The run is terminalized by the orchestrator; the still-live worker
   is not considered safe evidence for a handoff.

This prevents a successful handoff while a worker can still mutate shared
state. A read-only operation must not mutate Coraxis collaboration state, but
its callback, client, or future implementation could still touch process
state; therefore the barrier waits for lease release or refuses success.

### 6.3 Late result policy

When a timed-out worker returns:

- it may emit a bounded late-result diagnostic if the recorder is still
  available;
- it may not change `unknown` to `succeeded` or `failed`;
- it may not change the frozen handoff;
- it may not publish a normal success event;
- it may call `release_once` exactly once;
- it must not start another action after freeze/cancellation.

For a side-effecting worker, a late return after an ambiguous interruption is
always unsafe. The lease remains non-retryable even if the late result appears
successful. For a read-only worker, the late result can be recorded only as a
diagnostic; it does not make the timed-out action successful.

## 7. Required synchronization pseudocode

### 7.1 Normal read-only action and finalization

```text
invoke_read_only(tool, attempt, input):
    with coordination.lock:
        reject_if_cancelled_closed_or_frozen()
        enforce_memory_first(tool, attempt)
        seq = reserve_sequence()
        lease = register_started(
            seq=seq,
            attempt=attempt,
            tool=tool,
            side_effect=False,
        )
        lease.phase = "running"
        coordination.leases[seq] = lease
        coordination.in_flight_actions += 1

    try:
        result = perform_operation_outside_lock(input)
    except BaseException as exc:
        with coordination.lock:
            finalize_once(seq, "failed_or_unknown", classify(exc), "worker")
            release_once(seq, "worker")
        raise
    else:
        with coordination.lock:
            try:
                status = sanitize_and_store(result)
                finalize_once(seq, "succeeded", status, "worker")
            except BaseException:
                finalize_once(seq, "unknown", "result_recording_failed", "worker")
                raise UnsafeLedgerError
            finally:
                release_once(seq, "worker")
        return result
```

`failed_or_unknown` is resolved to `failed` only when the operation failure is
known and ledger recording succeeds. Otherwise it is `unknown`.

### 7.2 Read-only timeout while operation continues

```text
timeout_read_only(seq):
    with coordination.lock:
        coordination.cancellation_requested = True
        coordination.accepting_actions = False
        coordination.freeze_requested = True
        finalize_once(seq, "unknown", "read_timeout", "timeout-controller")
        # Deliberately do not release_once: worker is still alive.
        signal_worker_cancellation(seq)
        coordination.changed.notify_all()

    if not wait_for_worker_release(seq, grace_deadline):
        terminalize_run_without_handoff("read_worker_did_not_exit")
```

### 7.3 Late successful return after timeout

```text
late_success(seq, result):
    with coordination.lock:
        if lease_is_missing_or_released(seq):
            record_late_diagnostic_if_possible(seq, "late_after_release")
            return

        if lease.terminal_status == "unknown":
            record_late_diagnostic_if_possible(
                seq,
                "late_success_discarded",
                bounded_summary=result,
            )
            # First terminal transition remains unknown.
            release_once(seq, "late-worker")
            return

        # Only a still-started lease may be finalized by a normal worker.
        finalize_once(seq, "succeeded", sanitize(result), "late-worker")
        release_once(seq, "late-worker")
```

If the run has already frozen or terminalized, the diagnostic is best effort
and cannot alter run status, handoff, or normal event ordering.

### 7.4 Duplicate finalization

```text
finalize_once(seq, status, value, owner):
    with coordination.lock:
        lease = coordination.leases.get(seq)
        if lease is None:
            return ALREADY_FINALIZED_OR_RELEASED
        if lease.terminal_status != "started":
            return ALREADY_FINALIZED
        lease.terminal_status = status
        lease.terminal_owner = owner
        lease.finished_at = monotonic_now()
        store_bounded_value_or_mark_unknown(lease, value)
        coordination.changed.notify_all()
        return WON
```

Every caller treats `ALREADY_FINALIZED` as non-fatal and does not overwrite
the existing status. `release_once` has the same first-owner-wins behavior.

### 7.5 Freeze with read-only actions in flight

```text
freeze_for_handoff(raw_output, query):
    with coordination.lock:
        coordination.freeze_requested = True
        coordination.accepting_actions = False
        coordination.accepting_mutations = False
        coordination.changed.notify_all()

        while coordination.in_flight_actions > 0:
            if deadline_expired():
                for lease in live_leases():
                    if lease.side_effect:
                        finalize_once(
                            lease.seq,
                            "unknown",
                            "freeze_timeout_side_effect",
                            "freeze-controller",
                        )
                    else:
                        finalize_once(
                            lease.seq,
                            "unknown",
                            "freeze_timeout_read_only",
                            "freeze-controller",
                        )
                coordination.changed.notify_all()
                break
            coordination.changed.wait(timeout=remaining_deadline())

        if coordination.in_flight_actions != 0:
            terminalize_run_without_handoff("live_worker_at_freeze")
            raise UnsafeHandoffError

        if any_unknown_or_unrecorded_action():
            coordination.frozen = True
            raise UnsafeHandoffError

        collector.freeze_locked()
        channel.freeze_locked()
        collaboration = channel.snapshot_locked()
        records = collector.copy_records_locked()
        coordination.frozen = True

    return validate_and_build_immutable_handoff(
        query=query,
        raw_output=raw_output,
        records=records,
        collaboration=collaboration,
    )
```

The freeze controller may terminalize unresolved actions as unknown, but it
does not release their leases. A worker that remains alive prevents a
successful handoff. The orchestrator can still mark the run failed/timed out
and stop waiting, so cancellation does not deadlock or leave the run
permanently nonterminal.

## 8. Atomic channel snapshot

`AgentChannel` must expose a coordination-aware
`snapshot_locked()` returning:

```python
CollaborationSnapshot:
    version: int
    messages: tuple[Mapping[str, JSONValue], ...]
    blackboard: tuple[Mapping[str, JSONValue], ...]
```

The method is called only while `RunCoordination.lock` is held. `send()` and
`post()` are called only from the side-effect mutation phase while the same
lock is held. `freeze_locked()` rejects all later mutations and captures the
channel's closed state.

The ordering proof is now exact:

1. Mutation gate wins the lock first: it mutates, finalizes, and releases;
   freeze then snapshots the completed mutation.
2. Freeze wins the lock first: it closes admission and mutation; later
   mutation gates reject before operation, finalize, and do not alter channel
   state.
3. Read-only workers do not hold the lock; freeze waits for their leases to
   release. If a worker remains alive, handoff fails.

There is no state in which a side-effect action both holds the coordination
lock and waits for freeze permission.

## 9. Per-attempt memory-first enforcement

### 9.1 Attempt identity

The orchestrator allocates attempt numbers `1, 2, ...` under
`RunCoordination.lock`. Numbers are never reused. Every action stores both
`attempt` and global `seq`.

Each attempt has independent state:

```python
AttemptState:
    attempt: int
    memory_policy: Literal["enabled", "disabled"]
    first_action_seq: int | None
    first_action_tool: ToolName | None
    memory_first_state: Literal[
        "pending", "satisfied", "failed", "not_required", "violated"
    ]
```

When memory is enabled, `begin_tool_action()` rejects any first action other
than `recall_memory` before operation execution. A successful recall becomes
`satisfied`; a known recall failure becomes `failed`; an unresolved recall is
`unknown` and unsafe. When disabled, the state is `not_required` for every
attempt.

### 9.2 Retry after failed recall

A finalized failed recall is retained as failed and never represented as a
successful empty memory response. Because it is read-only, one fresh Protocol
A attempt may be allowed if the complete ledger contains no side effect,
unknown action, unrecorded result, collector failure, or freeze failure.

The next attempt gets a new number, resets its memory state to `pending`, and
must begin with a new `recall_memory` action. It cannot inherit or rewrite the
previous attempt's recall record.

Any attempted side effect in any attempt blocks all automatic Protocol A retry.
An unknown or unrecorded result also blocks retry. The controller evaluates the
complete run ledger, not only the latest attempt.

### 9.3 Attempt diagnostics

Bounded statistics must include:

```json
{
  "protocol_a_attempts": 2,
  "attempts": [
    {
      "attempt": 1,
      "first_action": {"seq": 1, "tool": "recall_memory"},
      "memory_first_state": "failed",
      "side_effect_attempted": false,
      "terminal_counts": {"succeeded": 0, "failed": 1, "unknown": 0}
    },
    {
      "attempt": 2,
      "first_action": {"seq": 2, "tool": "recall_memory"},
      "memory_first_state": "satisfied",
      "side_effect_attempted": false,
      "terminal_counts": {"succeeded": 2, "failed": 0, "unknown": 0}
    }
  ],
  "global_action_seq_range": [1, 2],
  "automatic_retry_allowed": false
}
```

No raw memory contents, credentials, headers, prompts, or private CrewAI
messages are persisted.

## 10. Retry matrix

| Complete-run condition | Automatic Protocol A retry |
|---|---:|
| Provider failure before any action | Yes, once |
| Finalized read-only failure only | Yes, once |
| Finalized failed recall only | Yes, once; next attempt recalls first |
| First action violates memory-first | No |
| Completed side effect in any attempt | No |
| Side effect entered mutation and became unknown | No |
| Admitted side effect rejected before operation | This action is not an attempted side effect; retry still requires all other ledger checks |
| Any unknown/unrecorded read-only action | No until its worker releases; then no if unknown remains part of failure policy |
| Collector/freeze/snapshot failure | No |
| Worker still alive at freeze deadline | No; fail without handoff |
| Memory disabled | Apply ordinary read-only/side-effect policy |

Protocol B retries remain formatter-only, reuse the exact immutable handoff,
and never create Protocol A attempts or invoke Protocol A tools.

## 11. Deterministic concurrency and retry tests

### 11.1 Side-effect and freeze races

1. Action registration occurs before any operation callback.
2. Mutation gate wins before freeze: mutation completes and appears in snapshot.
3. Freeze wins before mutation gate: action finalizes as pre-operation
   rejection, no channel mutation occurs, and snapshot excludes it.
4. Freeze never snapshots while a mutation is inside the coordination lock.
5. No side-effect operation performs network or unbounded work under the lock.
6. A mutation exception after entering the gate becomes unknown and blocks
   retry.
7. A post-freeze `send_message` is rejected without a channel entry.
8. A post-freeze `blackboard_write` is rejected without a blackboard entry.
9. No lock path acquires channel state before collector state.

### 11.2 Lease finalization and late completion

1. Normal success finalizes once and releases once.
2. Normal known failure finalizes failed and releases once.
3. Read-only timeout wins `unknown` while the worker continues; the lease
   remains in flight.
4. Freeze cannot build a handoff while that timed-out worker remains alive.
5. Worker exits after timeout: late success is discarded diagnostically and
   releases the lease exactly once.
6. Worker exits after timeout with failure: status remains unknown and release
   occurs exactly once.
7. Duplicate finalization returns `ALREADY_FINALIZED` and does not overwrite.
8. Duplicate release returns `ALREADY_RELEASED` and does not decrement twice.
9. Side-effect timeout/unknown blocks automatic Protocol A retry.
10. Cancellation and timeout terminalize the run without deadlock or a
    permanently nonterminal status.
11. A late worker cannot mutate a frozen channel or start a new action.
12. Process interruption tests document loss of in-memory knowledge and do not
    claim exactly-once execution.

### 11.3 Per-attempt memory-first

1. Attempt 1 begins with `recall_memory` when enabled.
2. Failed recall remains failed and may permit one retry only under the matrix.
3. Attempt 2 begins with a new `recall_memory`.
4. Attempt 2 cannot begin with `web_search`, `send_message`, or
   `blackboard_write`.
5. A successful or unknown side effect in either attempt blocks retry.
6. Disabled memory requires no recall in any attempt.
7. Every record includes attempt and global sequence.
8. Concurrent runs maintain independent attempt and memory-first state.

### 11.4 Handoff and downstream context

1. The channel snapshot contains one consistent version.
2. Handoff is immutable, redacted, run-local, and <= 65,536 UTF-8 bytes.
3. Protocol B formatter has zero tools and `SubQuestions`.
4. Web Searcher uses `context=[formatter_task]` only.
5. Analyst and Report Writer use immediate-predecessor contexts.
6. Protocol B retries reuse one handoff digest and never rerun Protocol A.

## 12. Events, persistence, and SSE

Use existing event types with bounded metadata:

```json
{
  "protocol": "A|B",
  "stage": "native_tools|handoff|structured_output",
  "attempt": 1,
  "action_seq": 7,
  "status": "started|succeeded|failed|unknown"
}
```

`EventRecorder` remains the only persistence/broadcast path. It must persist
before SSE publication. Late results may create a bounded diagnostic only if
the recorder is still active; they cannot create normal success events or
alter a frozen handoff.

Persist bounded action counts, attempt metadata, retry decisions, handoff
bytes, and digest. Do not persist raw handoffs, memory contents, credentials,
headers, unrestricted arguments, or private executor messages.

Cancellation and timeout close admission, terminalize unresolved leases where
possible, wait for release within a bounded grace period, then terminalize
the run without handoff if workers remain alive.

## 13. Implementation sequence and expected files

### Stage 0 — Contract and gate tests

Lock `SubQuestions`, provider gating, custom-team behavior, and explicit
immediate-predecessor contexts.

### Stage 1 — Run coordination and lease ledger

Expected files:

- [`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py)
- [`src/coraxis/agents/tools/crew_tools.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tools/crew_tools.py)

Implement `RunCoordination`, pre-operation action registration, side-effect
mutation gates, single-owner terminalization/release, timeout handling, and
per-attempt memory-first checks.

### Stage 2 — Atomic channel snapshot and freeze

Expected files:

- [`src/coraxis/agents/comms.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/comms.py)
- [`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py)

Implement coordination-aware `snapshot_locked()`, `freeze_locked()`, version
tracking, and immutable handoff copy/digest. Add race and late-completion
tests before adding CrewAI orchestration.

### Stage 3 — Protocol A builder

Expected files:

- [`src/coraxis/agents/tasks.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tasks.py)
- [`src/coraxis/agents/crew.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/crew.py)

Build the native-tool raw task with no structured output.

### Stage 4 — Protocol B and explicit contexts

Expected files:

- [`src/coraxis/agents/tasks.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tasks.py)
- [`src/coraxis/agents/crew.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/crew.py)

Build:

```text
formatter -> search(context=[formatter])
          -> analyse(context=[search])
          -> report(context=[analyse])
```

### Stage 5 — Orchestrator integration

Expected file:

- [`src/coraxis/services/research.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/services/research.py)

Integrate two kickoffs, attempt numbering, freeze barrier, immutable handoff,
stage retries, cancellation, events, stats, and unchanged final persistence.

### Stage 6 — Adapter regression

Expected test location:

- [`tests/unit/test_groq_compatibility.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/tests/unit/test_groq_compatibility.py)

Verify the existing adapter remains unchanged, preserves Protocol A tools, and
leaves Protocol B tools-free.

### Stage 7 — Isolated diagnostics

Use the isolated temporary environment without exposing credentials:

1. side-effect gate/freeze ordering;
2. read-only timeout and late completion;
3. per-attempt memory-first and failed-recall retry;
4. Protocol B with the same handoff digest;
5. one controlled end-to-end Groq pipeline case;
6. async, cancellation, persistence, SSE replay, and concurrent isolation.

Do not run the ten-case benchmark in this stage.

## 14. Rollback criteria and remaining limitations

Rollback the two-protocol gate if:

- any side-effect action mutates after freeze;
- a side-effect outcome is unknown but automatic retry is allowed;
- a terminal lease is overwritten or released twice;
- a late worker changes a frozen handoff or emits normal success;
- a live worker remains at freeze but a successful handoff is produced;
- memory-first is bypassed on any attempt;
- failed recall is fabricated as success;
- downstream context leaks Protocol A output;
- event/SSE ordering, terminal status, or external contracts change;
- non-Groq/custom behavior changes;
- secrets appear in diagnostics;
- controlled Groq execution still emits undeclared `json`/`JSON`.

Remaining limitations:

1. The ledger is in-memory and cannot prove what happened after process death.
2. It prevents duplicate automatic retries conservatively; it does not provide
   exactly-once provider/tool execution.
3. A future external side-effecting tool requires its own idempotency policy
   and must not hold the coordination lock across I/O.
4. A worker that ignores cancellation can force a failed run rather than a
   successful handoff; this is intentional.
5. Two kickoffs increase latency and token usage.
6. Late diagnostics are best effort after recorder shutdown.

## 15. Final confirmation

V4.1 is planning-only. No application source, tests, dependency manifests,
lockfiles, migrations, reports, baselines, evaluation outputs, live API calls,
benchmarks, commits, pushes, resets, cleans, stashes, discards, or overwrites
were performed.

**STOP CONDITION:** This document is the only deliverable. Wait for explicit
approval before implementation.

