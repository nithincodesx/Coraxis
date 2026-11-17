# Coraxis Researcher Two-Protocol Implementation Plan V4.2

## 1. Scope and preserved architecture

This is a narrow, planning-only correction to
[`CORAXIS_RESEARCHER_TWO_PROTOCOL_IMPLEMENTATION_PLAN_V4.1.md`](C:/Users/shulk/OneDrive/Desktop/Researcher/CORAXIS_RESEARCHER_TWO_PROTOCOL_IMPLEMENTATION_PLAN_V4.1.md).
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
- shared coordination lock and two-phase side-effect mutation gate;
- a redacted, immutable, run-local handoff capped at 65,536 UTF-8 bytes;
- existing Groq cache-marker adapter;
- no dependency changes or database migrations.

V4.2 corrects:

1. late workers must not sanitize/store normal results after timeout ownership
   has already won;
2. terminal status and prepared result/error record must publish atomically;
3. collaboration snapshots must be deeply detached and immutable.

The ledger provides exactly-once **lease finalization within the live process**,
not exactly-once tool execution or transactional durability across process
crashes.

## 2. Shared coordination and lease invariants

One run-local `RunCoordination` object remains the sole synchronization
authority for the collector, `ToolContext`, and `AgentChannel`:

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

The only lock order is:

```text
RunCoordination.lock -> collector state -> channel state
```

No coordinated operation acquires collector or channel state first.

Each accepted action has a lease with terminal states exactly:

```text
started | succeeded | failed | unknown
```

Lease release is a separate once-only transition. Terminalization and release
must never decrement `in_flight_actions` more than once.

## 3. Atomic terminalization with prepared records

### 3.1 Prepared record

The worker or timeout controller first creates a bounded, sanitized,
non-published record:

```python
PreparedTerminalRecord:
    status: Literal["succeeded", "failed", "unknown"]
    result_summary: FrozenJSON | None
    error_code: str
    prepared_by: str
```

Preparation performs no lease mutation, no terminal event publication, and no
normal result publication. It may occur outside `RunCoordination.lock` because
sanitization must not hold the coordination lock across unbounded work.

Known operation failures are prepared as `failed`. Ambiguous execution,
cancellation, timeout, or recording failures are prepared as `unknown`.

If preparation itself fails, create a minimal bounded
`unknown/result_recording_failed` preparation. If even that cannot be created,
the owner must acquire the lock and mark the lease unknown with a fixed
constant error code and no result payload, or fail the run if the lease is no
longer eligible.

### 3.2 `finalize_prepared_once`

Terminalization is one atomic critical section:

```text
finalize_prepared_once(seq, prepared, owner):
    with coordination.lock:
        lease = coordination.leases.get(seq)

        if lease is None or lease.released:
            return ALREADY_FINALIZED_OR_RELEASED

        if lease.terminal_status != "started":
            return ALREADY_FINALIZED

        # Eligibility check and publication are one lock-held transition.
        lease.result_summary = prepared.result_summary
        lease.error_code = prepared.error_code
        lease.terminal_status = prepared.status
        lease.terminal_owner = owner
        lease.finished_at = monotonic_now()
        notify changed
        return WON
```

The prepared record is fully available before the status changes. Therefore a
lease cannot become `succeeded` while its corresponding bounded result record
is missing.

If another owner won first, the caller discards the prepared normal result and
uses only the late-diagnostic path. It must not update the action record,
terminal status, frozen handoff, or normal success events.

### 3.3 Release remains separate

```text
release_once(seq, owner):
    with coordination.lock:
        lease = coordination.leases.get(seq)
        if lease is None or lease.released:
            return ALREADY_RELEASED

        lease.released = True
        lease.release_owner = owner
        coordination.leases.pop(seq)
        coordination.in_flight_actions -= 1
        coordination.changed.notify_all()
        return WON
```

`release_once` cannot change terminal status. A timeout may win
`unknown` while retaining the lease until the worker exits. The worker then
calls `release_once` exactly once even though its normal terminalization loses.

## 4. Correct normal completion and late-result protocol

### 4.1 Normal read-only completion

```text
complete_read_only(seq, operation_result):
    # No normal storage or event publication occurs before preparation.
    try:
        prepared = prepare_terminal_record(
            status="succeeded",
            result=sanitize_bounded_result(operation_result),
            error_code="",
            owner="worker",
        )
    except BaseException:
        prepared = prepare_unknown_record("result_recording_failed", "worker")

    outcome = finalize_prepared_once(seq, prepared, owner="worker")

    if outcome is WON:
        publish_normal_tool_success_if_run_open(seq, prepared)
    else:
        publish_late_diagnostic_if_possible(
            seq,
            "normal_result_discarded_terminal_owner_already_won",
            bounded_prepared_summary(prepared),
        )

    release_once(seq, owner="worker")
    if prepared.status == "unknown" and outcome is WON:
        raise UnsafeLedgerError
    return operation_result if outcome is WON else discard_normal_result()
```

The `publish_normal_tool_success_if_run_open` call must itself verify that the
action status is the worker's winning terminal status and that the run is not
frozen/terminalized. If that check loses a race, it publishes only a bounded
diagnostic. Normal events are never emitted by a non-winning owner.

For a known operation exception, prepare `failed` with a bounded error code,
then use the same `finalize_prepared_once` path. If the exception's outcome is
ambiguous, prepare `unknown`.

### 4.2 Timeout followed by late success

```text
timeout_read_only(seq):
    with coordination.lock:
        coordination.cancellation_requested = True
        coordination.accepting_actions = False
        coordination.freeze_requested = True

    prepared = prepare_unknown_record("read_timeout", "timeout-controller")
    outcome = finalize_prepared_once(seq, prepared, "timeout-controller")

    # Deliberately retain the lease while the worker is alive.
    signal_worker_cancellation(seq)
    if outcome is WON:
        publish_unknown_event_if_run_open(seq)

late_success(seq, result):
    prepared = prepare_terminal_record(
        status="succeeded",
        result=sanitize_bounded_result(result),
        error_code="",
        owner="late-worker",
    )
    outcome = finalize_prepared_once(seq, prepared, "late-worker")

    if outcome is ALREADY_FINALIZED:
        publish_late_diagnostic_if_possible(
            seq,
            "late_success_discarded_after_unknown",
            bounded_prepared_summary(prepared),
        )
    elif outcome is WON:
        # This is only possible if the timeout failed to win and the lease
        # was still started. It is a normal worker win, not a late overwrite.
        publish_normal_tool_success_if_run_open(seq, prepared)

    release_once(seq, "late-worker")
```

If the timeout controller won `unknown`, the late worker cannot overwrite it.
The late result is not stored in the normal action record and cannot affect a
frozen handoff.

### 4.3 Timeout followed by late failure

```text
late_failure(seq, known_error):
    prepared = prepare_terminal_record(
        status="failed",
        result=None,
        error_code=classify_known_error(known_error),
        owner="late-worker",
    )
    outcome = finalize_prepared_once(seq, prepared, "late-worker")

    if outcome is ALREADY_FINALIZED:
        publish_late_diagnostic_if_possible(
            seq,
            "late_failure_discarded_after_unknown",
            {"error_code": prepared.error_code},
        )
    elif outcome is WON:
        publish_normal_tool_failure_if_run_open(seq, prepared)

    release_once(seq, "late-worker")
```

When timeout already won `unknown`, the late known failure is diagnostic only;
the action remains `unknown`.

### 4.4 Duplicate finalization

```text
duplicate_finalization(seq, prepared, owner):
    outcome = finalize_prepared_once(seq, prepared, owner)
    if outcome in {ALREADY_FINALIZED, ALREADY_FINALIZED_OR_RELEASED}:
        discard_prepared_normal_record(prepared)
        publish_late_diagnostic_if_possible(
            seq,
            "duplicate_terminalization",
            {"owner": owner},
        )
    return outcome
```

Two competing terminalization owners cannot both win because eligibility check
and publication occur under the same coordination lock.

## 5. Side-effecting mutation and freeze

The V4.1 two-phase side-effect protocol remains:

1. Under `coordination.lock`, register `started` before operation execution.
2. At the mutation gate, reacquire the same lock.
3. If freeze has begun, finalize the admitted action as known `failed` with
   `mutation_rejected_after_freeze`; release it; do not mutate.
4. Otherwise, mark the lease running and perform only the bounded local
   `AgentChannel` mutation while holding the lock.
5. Prepare the bounded success/failure/unknown record.
6. Publish the prepared terminal record atomically while still holding the
   lock, then release once.

No network, provider call, filesystem operation, or unbounded work may hold
the coordination lock. Freeze uses that same lock, so it either follows a
completed mutation or closes the mutation gate before it begins. It never
snapshots during a mutation.

If a side-effect operation enters mutation and its outcome is ambiguous, its
prepared status is `unknown`; it blocks all automatic Protocol A retry. A
late side-effect result is never allowed to change a frozen handoff or permit
retry.

## 6. Deeply detached immutable collaboration snapshots

### 6.1 Snapshot contract

`AgentChannel.snapshot_locked()` is called only while
`RunCoordination.lock` is held and returns a detached snapshot:

```python
CollaborationSnapshot:
    version: int
    messages: tuple[FrozenMapping[str, FrozenJSON], ...]
    blackboard: tuple[FrozenMapping[str, FrozenJSON], ...]
```

The exact concrete frozen-map type may be a recursive immutable mapping
wrapper, but a tuple containing ordinary mutable dictionaries is insufficient.

### 6.2 Deep-copy procedure

While holding `RunCoordination.lock`, `snapshot_locked()` must:

1. read the channel version;
2. recursively copy each message and blackboard entry;
3. recursively convert nested lists to tuples;
4. recursively convert nested dictionaries to immutable/read-only mappings;
5. copy scalar values into the snapshot representation;
6. capture the same version marker after copying, or verify it did not change;
7. return only detached immutable values.

Because all channel mutations also require `RunCoordination.lock`, the version
cannot change during this operation. The version and both collections are
therefore one atomic view.

No live `AgentMessage`, blackboard entry, mutable dict, list, object reference,
or channel-owned value may escape into the snapshot.

### 6.3 Handoff and digest

The handoff builder receives only:

```text
copied collector records
detached CollaborationSnapshot
bounded Protocol A raw output
query
```

It serializes and hashes those detached values only. It never serializes the
live channel or collector. After construction, mutations to the original
channel or collector cannot change the handoff bytes or digest.

The 65,536-byte UTF-8 cap and redaction rules remain unchanged. If deep-copy,
redaction, serialization, or digest preparation fails, no successful handoff
is produced.

### 6.4 Freeze ordering

Successful freeze requires:

```text
coordination.freeze_requested = True
accepting_actions = False
accepting_mutations = False
in_flight_actions == 0
no lease has unresolved/unknown status
collector and channel frozen under coordination.lock
detached channel snapshot captured under coordination.lock
handoff built only from detached values
```

A read-only worker that has timed out and is still alive keeps its lease and
prevents successful handoff. A worker that returns later can release its lease
once, but cannot rewrite its terminal status or handoff.

## 7. Per-attempt memory-first and retry protection

Attempt numbers remain monotonically increasing and are assigned under
`RunCoordination.lock`. Every action stores both `attempt` and global `seq`.

For every fresh Protocol A attempt when memory is enabled:

```text
pending
  -> only recall_memory may be first admitted action
  -> recall success: satisfied
  -> known recall failure: failed
  -> ambiguous/recording failure: unknown/unsafe
```

When memory is disabled, the attempt starts `not_required`.

A finalized failed recall may permit one fresh Protocol A attempt only when the
complete run ledger contains no side effect, unknown/unrecorded action,
collector failure, freeze failure, or live worker. The next attempt receives a
new number and must begin with a new `recall_memory`. A failed recall is never
represented as a successful empty result.

Any attempted side effect in any attempt blocks automatic retry for the whole
run. Any unknown or unrecorded action also blocks retry. Protocol B retries
remain formatter-only and reuse the exact immutable handoff.

## 8. Retry decision matrix

| Complete-run condition | Automatic Protocol A retry |
|---|---:|
| Provider failure before any action | Yes, once |
| Finalized read-only failure only | Yes, once |
| Finalized failed recall only | Yes, once; next attempt recalls first |
| First action violates memory-first | No |
| Completed side effect | No |
| Unknown/unrecorded side effect | No |
| Unknown/unrecorded read-only action | No while live; no safe handoff after unknown |
| Collector, preparation, freeze, snapshot, or digest failure | No |
| Live worker at freeze deadline | No; fail without handoff |
| Memory disabled | Apply ordinary read-only/side-effect policy |

## 9. Required deterministic tests

### 9.1 Atomic terminalization and late results

1. Normal success prepares its bounded result before terminal publication.
2. Normal known failure publishes `failed` only with a prepared error record.
3. Result sanitization failure publishes `unknown`, never `succeeded`.
4. Timeout wins `unknown`; a late success cannot store a normal result.
5. Timeout wins `unknown`; a late failure cannot overwrite it.
6. Two competing terminalization owners cannot both return `WON`.
7. A losing owner uses only the bounded late-diagnostic path.
8. Duplicate finalization does not alter status, result, owner, or timestamp.
9. Duplicate release does not decrement `in_flight_actions` twice.
10. A normal success event is emitted only by the winning terminal owner.
11. A late result after freeze cannot modify the handoff or emit normal success.

### 9.2 Side-effect/freeze races

1. Registration precedes every side-effect operation.
2. Mutation gate wins before freeze: mutation is included in the snapshot.
3. Freeze wins before mutation gate: action is known `failed` rejection and no
   channel mutation occurs.
4. Freeze never snapshots while a mutation is in progress.
5. Side-effect ambiguity becomes `unknown` and blocks retry.
6. No external or unbounded operation holds the coordination lock.

### 9.3 Detached atomic snapshots

1. Snapshot version and contents are captured under one coordination lock.
2. Deeply nested original message/blackboard values can be mutated after
   snapshot without changing snapshot contents.
3. Original channel mutation after snapshot cannot change the snapshot digest.
4. Snapshot contains no live channel objects, mutable dicts, or mutable lists.
5. A successful handoff contains no live worker lease.
6. A live worker at freeze prevents successful handoff.
7. Concurrent channel writers produce either pre-freeze content or rejection.
8. Two runs have independent channels, snapshots, and digests.

### 9.4 Per-attempt and downstream tests

1. Attempt 1 begins with `recall_memory` when enabled.
2. Failed recall remains failed and a permitted attempt 2 recalls first again.
3. Attempt 2 cannot begin with another tool when memory is enabled.
4. A side effect or unknown action in either attempt blocks retry.
5. Disabled memory requires no recall in any attempt.
6. Every action records attempt and global sequence.
7. Protocol A has native tools and no structured output.
8. Protocol B has no tools and valid `SubQuestions`.
9. Web Searcher uses `context=[formatter_task]` only.
10. Protocol B retry reuses one handoff digest and never reruns Protocol A.

## 10. Events, persistence, and SSE

`EventRecorder` remains the only persistence/broadcast path and persists
before SSE publication. Events include only bounded metadata:

```json
{
  "protocol": "A|B",
  "stage": "native_tools|handoff|structured_output",
  "attempt": 1,
  "action_seq": 7,
  "status": "started|succeeded|failed|unknown"
}
```

Late results may produce bounded diagnostics if the recorder remains active.
They cannot modify normal action records after a winning terminal transition,
change a frozen handoff, or create normal success events.

Persist bounded action counts, attempt metadata, retry decisions, handoff size,
and digest. Do not persist raw handoffs, memory contents, credentials,
headers, unrestricted arguments, or private CrewAI messages.

Cancellation and timeout close admission, terminalize unresolved actions where
possible, wait for lease release within a bounded grace period, and
terminalize the run without handoff if a worker remains alive.

## 11. Implementation sequence and expected files

The approved sequence remains:

1. Contract and provider-gate tests.
2. `RunCoordination`, collector preparation/terminalization/release, and
   per-attempt memory-first enforcement.
3. Coordination-aware channel freeze, deep detached snapshot, and digest.
4. Protocol A raw native-tool builder.
5. Protocol B no-tools formatter and explicit predecessor contexts.
6. Orchestrator integration, retries, cancellation, events, and stats.
7. Existing Groq adapter regression tests.
8. Isolated diagnostics, followed only after gates by a controlled
   four-agent live run.

Expected production files remain:

- [`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py)
- [`src/coraxis/agents/tools/crew_tools.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tools/crew_tools.py)
- [`src/coraxis/agents/comms.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/comms.py)
- [`src/coraxis/agents/tasks.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tasks.py)
- [`src/coraxis/agents/crew.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/crew.py)
- [`src/coraxis/services/research.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/services/research.py)

Expected tests cover collector lifecycle, late completion, freeze races,
deep-detached snapshots, memory-first attempts, context isolation, events,
persistence, and the existing Groq adapter. No dependency manifests,
migrations, external contracts, `SubQuestions`, existing reports, or baseline
data should change.

## 12. Rollback criteria and limitations

Rollback the two-protocol gate if:

- a late worker overwrites `unknown` or stores a normal result after losing
  terminal ownership;
- two terminalization or release owners can both win;
- result preparation/storage fails but the action becomes `succeeded` or
  safely retryable;
- a live worker is present in a successful handoff;
- a mutable channel reference escapes into a snapshot;
- a mutation occurs after freeze;
- memory-first is bypassed on any attempt;
- unknown/unrecorded side effects permit retry;
- downstream context, events, terminal status, non-Groq behavior, custom-team
  behavior, secrets, or external contracts regress;
- controlled Groq execution still emits undeclared `json`/`JSON`.

Remaining limitations:

1. The ledger is in-memory and cannot establish what happened after process
   death.
2. Exactly-once lease finalization in a live process is not exactly-once tool
   execution.
3. External side-effecting tools require separate idempotency design and must
   not hold the coordination lock across I/O.
4. A worker that ignores cancellation can force a failed run instead of a
   successful handoff.
5. Late diagnostics after recorder shutdown are best effort.
6. Two kickoffs increase latency and token usage.

## 13. Final planning-only confirmation

V4.2 is planning-only and does not authorize implementation. No application
source, tests, dependencies, migrations, reports, baselines, evaluation
outputs, live API calls, benchmarks, commits, pushes, resets, cleans, stashes,
discards, or overwrites were performed.

**STOP CONDITION:** This document is the only deliverable. Wait for explicit
approval.

