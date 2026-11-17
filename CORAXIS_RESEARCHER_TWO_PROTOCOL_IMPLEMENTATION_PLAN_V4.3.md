# Coraxis Researcher Two-Protocol Implementation Plan V4.3

## 1. Scope and preserved architecture

This is a planning-only correction to
[`CORAXIS_RESEARCHER_TWO_PROTOCOL_IMPLEMENTATION_PLAN_V4.2.md`](C:/Users/shulk/OneDrive/Desktop/Researcher/CORAXIS_RESEARCHER_TWO_PROTOCOL_IMPLEMENTATION_PLAN_V4.2.md).
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

V4.3 corrects one remaining ownership flaw in V4.2: a worker must establish
that it owns normal-result preparation before it sanitizes or prepares that
result. A worker whose lease is already terminalized as `unknown` must not
enter normal preparation at all.

The ledger provides exactly-once **lease terminalization and release within
the live process**, not exactly-once tool execution or transactional
durability across process crashes.

## 2. Shared coordination and lease model

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

The only lock order remains:

```text
RunCoordination.lock -> collector state -> channel state
```

No coordinated operation acquires collector or channel state first. No
external, network, filesystem, provider, or unbounded sanitization operation
may hold `RunCoordination.lock`.

## 3. Complete lease states and transitions

Each accepted action has one lease. Its lifecycle has independent preparation,
terminalization, and release state:

```python
ActionLease:
    seq: int
    attempt: int
    side_effecting: bool
    terminal_status: Literal["started", "succeeded", "failed", "unknown"]
    preparation_owner: Literal["none", "worker", "timeout-controller"]
    preparation_state: Literal["not_started", "claimed", "prepared", "abandoned"]
    terminal_owner: str | None
    result_summary: FrozenJSON | None
    error_code: str
    released: bool
```

The externally visible terminal statuses are exactly:

```text
started | succeeded | failed | unknown
```

`preparation_owner` and `preparation_state` are internal coordination fields,
not terminal statuses. `released` is also independent from terminalization.

### 3.1 Admission and registration

Under `RunCoordination.lock`, every action:

1. reserves a unique global `seq`;
2. records its Protocol A attempt number;
3. records whether it can have side effects;
4. creates a lease with `terminal_status="started"`;
5. increments `in_flight_actions`;
6. emits or queues the bounded started record.

No operation executes before registration succeeds. If registration fails,
the operation must not execute and the run fails conservatively.

### 3.2 Preparation ownership

Only the owner that successfully changes `preparation_state` from
`not_started` to `claimed` may perform normal preparation. This claim is made
under `RunCoordination.lock`.

The claim is deliberately not terminalization. The timeout controller may
still terminalize the lease as `unknown` while the worker is preparing. The
worker therefore must re-check terminal eligibility when it publishes its
prepared record.

### 3.3 Terminalization

The first owner that changes `terminal_status` from `started` to a terminal
status wins. Status publication and its prepared record are one lock-held
transition. A losing owner cannot publish a normal result, error, or success
event.

Known operation failures are `failed`. Ambiguous execution, timeout,
cancellation, preparation, recording, or collector failures are `unknown`.

### 3.4 Release

`release_once` is a separate once-only transition. It can be performed only
after the action has a terminal status, or when the run is being conservatively
aborted with a fixed `unknown` record. The first release marks `released` and
decrements `in_flight_actions`; subsequent releases are no-ops.

## 4. Ownership protocol for normal worker results

### 4.1 Worker claims preparation ownership before sanitization

```text
worker_complete(seq, operation_result):
    with coordination.lock:
        lease = coordination.leases.get(seq)

        if lease is None or lease.released:
            return late_diagnostic("lease_missing_or_released")

        if lease.terminal_status != "started":
            # Includes timeout-owned unknown.
            return late_diagnostic("terminal_owner_already_won")

        if lease.preparation_state != "not_started":
            return late_diagnostic("preparation_owner_already_claimed")

        lease.preparation_owner = "worker"
        lease.preparation_state = "claimed"

    # The lock is released before any potentially unbounded work.
    return prepare_worker_result(seq, operation_result)
```

The worker checks terminal status and reserves preparation ownership in the
same critical section. If timeout has already won `unknown`, the worker
returns through the late-diagnostic path without invoking
`sanitize_bounded_result` or any other normal-result preparation.

### 4.2 Worker prepares outside the lock

```text
prepare_worker_result(seq, operation_result):
    try:
        prepared = prepare_terminal_record(
            status="succeeded",
            result=sanitize_bounded_result(operation_result),
            error_code="",
            owner="worker",
        )
    except KnownOperationError as error:
        prepared = prepare_terminal_record(
            status="failed",
            result=None,
            error_code=bounded_known_error_code(error),
            owner="worker",
        )
    except BaseException:
        prepared = prepare_unknown_record(
            "result_recording_failed",
            owner="worker",
        )

    with coordination.lock:
        lease = coordination.leases.get(seq)
        if lease is None or lease.released:
            discard_prepared_record(prepared)
            return late_diagnostic("lease_missing_after_preparation")

        if lease.terminal_status != "started":
            # Timeout may have won while preparation was in progress.
            discard_prepared_record(prepared)
            return late_diagnostic("prepared_result_lost_terminal_race")

        if lease.preparation_owner != "worker":
            discard_prepared_record(prepared)
            return late_diagnostic("worker_preparation_ownership_lost")

        lease.preparation_state = "prepared"
        lease.result_summary = prepared.result_summary
        lease.error_code = prepared.error_code
        lease.terminal_status = prepared.status
        lease.terminal_owner = "worker"
        lease.finished_at = monotonic_now()
        coordination.changed.notify_all()

    publish_normal_event_only_if_worker_terminal_owner(seq, prepared)
    release_once(seq, owner="worker")
    return operation_result
```

The final eligibility check, prepared-record publication, and terminal status
publication occur atomically under `RunCoordination.lock`. Normal preparation
does not.

If preparation fails and the worker can still terminalize, it publishes
`unknown/result_recording_failed`. It never publishes `succeeded` without a
valid prepared record.

## 5. Timeout and worker races

### 5.1 Timeout wins before worker claims ownership

```text
timeout_action(seq):
    with coordination.lock:
        lease = coordination.leases.get(seq)
        if lease is None or lease.released:
            return already_terminal_or_released

        if lease.terminal_status != "started":
            return already_terminal

        # Timeout may claim the preparation slot only for diagnostics.
        lease.preparation_owner = "timeout-controller"
        lease.preparation_state = "claimed"

        lease.result_summary = None
        lease.error_code = "read_timeout_or_cancellation"
        lease.terminal_status = "unknown"
        lease.terminal_owner = "timeout-controller"
        lease.finished_at = monotonic_now()
        coordination.changed.notify_all()

    signal_worker_cancellation(seq)
    publish_unknown_event_if_run_open(seq)
    # Retain the lease until the worker exits and releases it.
```

If the worker attempts to claim after this transition, it sees
`terminal_status != "started"` and does not prepare or sanitize its result.

### 5.2 Timeout wins while worker is preparing

The worker has `preparation_owner="worker"` and
`preparation_state="claimed"`, but this does not reserve terminalization.
Timeout may acquire the lock and publish `unknown`:

```text
timeout_while_worker_prepares(seq):
    with coordination.lock:
        lease = coordination.leases[seq]
        if lease.terminal_status == "started":
            lease.result_summary = None
            lease.error_code = "read_timeout_or_cancellation"
            lease.terminal_status = "unknown"
            lease.terminal_owner = "timeout-controller"
            lease.finished_at = monotonic_now()
            coordination.changed.notify_all()

    signal_worker_cancellation(seq)
```

The worker may finish its already-started sanitization, but its final
lock-held check sees `unknown`, discards the prepared record, emits only a
bounded late diagnostic, and releases its lease exactly once. It cannot change
the timeout-owned status or handoff.

### 5.3 Worker finishes preparation and wins

```text
worker_preparation_wins(seq, prepared):
    with coordination.lock:
        lease = coordination.leases[seq]
        if (
            lease.terminal_status != "started"
            or lease.preparation_owner != "worker"
        ):
            discard_prepared_record(prepared)
            return LOST

        lease.preparation_state = "prepared"
        lease.result_summary = prepared.result_summary
        lease.error_code = prepared.error_code
        lease.terminal_status = prepared.status
        lease.terminal_owner = "worker"
        lease.finished_at = monotonic_now()
        coordination.changed.notify_all()
        return WON

if worker_preparation_wins(seq, prepared) is WON:
    publish_normal_event_only_if_worker_terminal_owner(seq, prepared)
else:
    publish_late_diagnostic_if_possible(seq, "normal_result_discarded")
release_once(seq, "worker")
```

Only this winning path can publish a normal success or failure event.

### 5.4 Worker finishes preparation but loses

```text
worker_preparation_loses(seq, prepared):
    with coordination.lock:
        lease = coordination.leases.get(seq)
        if lease is None or lease.terminal_status != "started":
            # Timeout or another owner already won.
            discard_prepared_record(prepared)
            return LOST

        # A competing owner may be selected by the same critical section.
        return worker_preparation_wins(seq, prepared)

if outcome is LOST:
    publish_late_diagnostic_if_possible(
        seq,
        "prepared_result_discarded_after_terminalization",
    )
    release_once(seq, "worker")
```

The losing worker cannot update the normal action record, terminal status,
frozen handoff, or normal success events.

### 5.5 Late success and late failure

If the worker did not claim preparation before timeout won, late completion
must not enter normal preparation:

```text
late_success(seq, raw_result):
    with coordination.lock:
        lease = coordination.leases.get(seq)
        if lease is None or lease.terminal_status != "started":
            return late_diagnostic("late_success_without_terminal_ownership")

        # A still-started lease may claim only if this is genuinely the
        # first completion path; otherwise the caller is not a late worker.
        if lease.preparation_state != "not_started":
            return late_diagnostic("late_success_preparation_not_available")

        lease.preparation_owner = "worker"
        lease.preparation_state = "claimed"

    prepared = prepare_terminal_record(
        status="succeeded",
        result=sanitize_bounded_result(raw_result),
        error_code="",
        owner="late-worker",
    )
    return publish_if_still_owned_or_diagnose(seq, prepared, "late-worker")
```

In the normal timeout case, the first lock-held check returns diagnostic-only,
so no sanitization occurs. If a timeout request lost the race and the lease
remains `started`, this is a normal first completion, not an overwrite.

```text
late_failure(seq, known_error):
    with coordination.lock:
        lease = coordination.leases.get(seq)
        if lease is None or lease.terminal_status != "started":
            return late_diagnostic("late_failure_without_terminal_ownership")
        if lease.preparation_state != "not_started":
            return late_diagnostic("late_failure_preparation_not_available")
        lease.preparation_owner = "worker"
        lease.preparation_state = "claimed"

    prepared = prepare_terminal_record(
        status="failed",
        result=None,
        error_code=bounded_known_error_code(known_error),
        owner="late-worker",
    )
    return publish_if_still_owned_or_diagnose(seq, prepared, "late-worker")
```

When timeout owns `unknown`, both late paths are bounded diagnostics only.

## 6. Duplicate terminalization and release

### 6.1 Duplicate terminalization

```text
finalize_prepared_once(seq, prepared, owner):
    with coordination.lock:
        lease = coordination.leases.get(seq)
        if lease is None or lease.released:
            return ALREADY_FINALIZED_OR_RELEASED
        if lease.terminal_status != "started":
            return ALREADY_FINALIZED
        if lease.preparation_owner != owner:
            return NOT_PREPARATION_OWNER

        lease.preparation_state = "prepared"
        lease.result_summary = prepared.result_summary
        lease.error_code = prepared.error_code
        lease.terminal_status = prepared.status
        lease.terminal_owner = owner
        lease.finished_at = monotonic_now()
        coordination.changed.notify_all()
        return WON
```

The eligibility check and prepared-record/status publication are one critical
section. Two owners cannot both return `WON`. A losing owner discards its
prepared record and emits only a bounded late diagnostic.

### 6.2 Duplicate release

```text
release_once(seq, owner):
    with coordination.lock:
        lease = coordination.leases.get(seq)
        if lease is None or lease.released:
            return ALREADY_RELEASED
        if lease.terminal_status == "started":
            return NOT_TERMINAL

        lease.released = True
        lease.release_owner = owner
        coordination.leases.pop(seq)
        coordination.in_flight_actions -= 1
        coordination.changed.notify_all()
        return WON
```

The first release is the only decrement. A late worker must call release even
after losing terminalization, but a second callback cannot decrement again.

## 7. Side-effect preparation and freeze lifecycle

The existing two-phase side-effect mutation gate is preserved:

1. Register the action as `started` under `RunCoordination.lock` before any
   operation.
2. Perform external or unbounded work outside the lock.
3. Reacquire the lock at the mutation gate.
4. If freeze has begun, finalize known `failed` with
   `mutation_rejected_after_freeze`; do not mutate.
5. Otherwise, perform only the bounded local `AgentChannel` mutation while
   holding the lock.
6. Release the lock before preparing/sanitizing the result.
7. Claim preparation ownership under the lock before any normal preparation.
8. Prepare the bounded result outside the lock.
9. Reacquire the lock and publish the prepared record plus terminal status only
   if the lease is still `started` and owned by this preparation path.
10. Release the lease exactly once.

No external work or unbounded sanitization occurs while the coordination lock
is held. Freeze uses that same lock, so it either follows a completed local
mutation or closes the mutation gate before it begins. No side-effecting
mutation can cross the freeze boundary.

If a side-effect outcome is ambiguous, terminalize `unknown`; it blocks all
automatic Protocol A retry. A late side-effect result cannot alter the frozen
handoff or permit retry.

## 8. Atomic detached collaboration snapshot

`AgentChannel.snapshot_locked()` remains called only while
`RunCoordination.lock` is held. It recursively copies messages and blackboard
entries, converts lists to tuples, converts nested dictionaries to immutable
read-only mappings, captures one stable version, and returns no live channel
references:

```python
CollaborationSnapshot:
    version: int
    messages: tuple[FrozenMapping[str, FrozenJSON], ...]
    blackboard: tuple[FrozenMapping[str, FrozenJSON], ...]
```

Handoff serialization and digest calculation use only this detached snapshot,
copied collector records, bounded raw Protocol A output, and the query. They
never serialize live channel or lease objects. Mutating the original channel
after snapshot cannot change the snapshot or digest.

Successful freeze requires closed action/mutation admission, zero live leases,
no unresolved or unknown action, a frozen collector/channel, and a detached
snapshot captured under the same lock. A worker that remains alive prevents a
successful handoff.

## 9. Per-attempt memory-first and retry policy

Every Protocol A attempt receives a monotonically increasing number under the
coordination lock, and every action records both its `attempt` and `seq`.

When memory is enabled, the first admitted action of every fresh attempt must
be `recall_memory`; the guarded registry rejects any other first action before
operation execution. A failed recall remains `failed`, never a fabricated
successful empty result. A finalized read-only recall failure may permit one
fresh attempt only if no side effect, unknown/unrecorded action, collector
failure, freeze failure, or live worker exists. The next attempt performs its
own first recall.

Any attempted side effect in any attempt blocks automatic Protocol A retry.
Any unknown or unrecorded action blocks retry. Protocol B retries remain
formatter-only and reuse the exact immutable handoff.

## 10. Retry decision matrix

| Complete-run condition | Automatic Protocol A retry |
|---|---:|
| Provider failure before any action | Yes, once |
| Finalized read-only failure only | Yes, once |
| Finalized failed recall only | Yes, once; next attempt recalls first |
| Worker loses preparation ownership | No new retry unless the loss was only a finalized read-only failure and no unsafe state exists |
| Completed side effect | No |
| Unknown/unrecorded side effect | No |
| Unknown/unrecorded read-only action | No while live; no safe handoff after unknown |
| Preparation, collector, freeze, snapshot, or digest failure | No |
| Live worker at freeze deadline | No; fail without handoff |
| Memory disabled | Apply ordinary read-only/side-effect policy |

## 11. Required deterministic tests

### 11.1 Ownership and terminalization

1. A worker whose lease is already `unknown` cannot claim preparation.
2. No normal sanitization call occurs after timeout wins before the claim.
3. Timeout wins while worker preparation is in progress.
4. The worker discards its prepared record after losing terminalization.
5. A losing worker cannot publish a normal result or success event.
6. Exactly one terminalization owner returns `WON`.
7. Prepared record and terminal status become visible atomically.
8. Result-preparation failure publishes `unknown`, never `succeeded`.
9. Duplicate terminalization cannot change status, owner, record, or timestamp.
10. Duplicate release cannot decrement `in_flight_actions` twice.
11. Late success and late failure after timeout use only bounded diagnostics.

### 11.2 Side-effect and freeze races

1. Registration precedes every side-effect operation.
2. Mutation before freeze is included in the snapshot.
3. Freeze before mutation rejects the mutation and performs no channel write.
4. No side-effecting mutation occurs after the freeze boundary.
5. An ambiguous side-effect result becomes `unknown` and blocks retry.
6. No external, network, filesystem, provider, or unbounded operation holds
   `RunCoordination.lock`.

### 11.3 Detached snapshots

1. Snapshot version and contents are captured under one coordination lock.
2. Deep mutation of original channel values cannot change snapshot contents.
3. Original channel mutation cannot change the snapshot digest.
4. No mutable mapping, list, live channel object, or worker lease escapes.
5. A live worker prevents successful handoff.
6. Concurrent runs maintain independent ledgers, channels, snapshots, and
   digests.

### 11.4 Protocol and retry behavior

1. Every enabled-memory attempt begins with `recall_memory`.
2. A failed recall remains failed; an allowed retry recalls first again.
3. A second attempt cannot begin with `web_search` when memory is enabled.
4. A side effect or unknown action in either attempt blocks retry.
5. Disabled memory requires no recall.
6. Protocol A has native tools without structured output.
7. Protocol B has no tools and valid `SubQuestions`.
8. Explicit immediate-predecessor contexts exclude raw Protocol A output.
9. Protocol B retry reuses one immutable handoff and never reruns Protocol A.

## 12. Events, persistence, and SSE

`EventRecorder` remains the only persistence/broadcast path and persists
before SSE publication. Bounded metadata includes protocol, stage, attempt,
action sequence, and one of the four terminal statuses.

Only the terminalization owner that wins the lock-held transition may publish
a normal success or failure event. A timeout owner may publish the bounded
`unknown` event. A losing or late worker may publish only a bounded diagnostic
if recording remains available; it cannot modify normal records, terminal
status, frozen handoff, or normal success events.

Persist bounded action counts, attempts, retry decisions, handoff size, and
digest. Do not persist raw handoffs, memory contents, credentials, headers,
unrestricted arguments, or private CrewAI messages.

## 13. Implementation sequence and expected files

The approved implementation sequence remains:

1. Contract and provider-gate tests.
2. `RunCoordination`, pre-operation ledger registration, preparation
   ownership, atomic terminalization, release, and memory-first enforcement.
3. Coordination-aware channel freeze, deep detached snapshot, and digest.
4. Protocol A raw native-tool builder.
5. Protocol B no-tools formatter and explicit predecessor contexts.
6. Orchestrator integration, retries, cancellation, events, and statistics.
7. Existing Groq adapter regression tests.
8. Isolated diagnostics, followed only after gates by one controlled
   four-agent live run.

Expected production files remain:

- [`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py)
- [`src/coraxis/agents/tools/crew_tools.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tools/crew_tools.py)
- [`src/coraxis/agents/comms.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/comms.py)
- [`src/coraxis/agents/tasks.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tasks.py)
- [`src/coraxis/agents/crew.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/crew.py)
- [`src/coraxis/services/research.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/services/research.py)

Expected tests cover ownership races, collector lifecycle, late completion,
freeze races, detached snapshots, memory-first attempts, context isolation,
events, persistence, and the existing Groq adapter. No dependency manifests,
migrations, external contracts, `SubQuestions`, existing reports, or baseline
data should change.

## 14. Rollback criteria and remaining limitations

Rollback the two-protocol gate if:

- a worker sanitizes after timeout already owns `unknown`;
- two preparation or terminalization owners can both win;
- a losing worker stores a normal result or emits a normal success event;
- prepared result storage and terminal status are not atomic;
- duplicate release decrements the in-flight count;
- a side-effect mutation crosses the freeze boundary;
- an unbounded operation holds the coordination lock;
- a live worker or mutable channel reference enters a successful handoff;
- memory-first is bypassed on any attempt;
- unknown/unrecorded side effects permit retry;
- downstream context, events, terminal status, non-Groq behavior, custom-team
  behavior, secrets, or external contracts regress;
- controlled Groq execution still emits undeclared `json`/`JSON`.

Remaining limitations:

1. The ledger is in-memory and cannot establish what happened after process
   death.
2. Exactly-once live-process lease finalization is not exactly-once tool
   execution.
3. External side effects require separate idempotency design.
4. A worker that ignores cancellation can force a failed run instead of a
   successful handoff.
5. Late diagnostics after recorder shutdown are best effort.
6. Two kickoffs increase latency and token usage.

## 15. Final planning-only confirmation

V4.3 is planning-only and does not authorize implementation. No application
source, tests, dependencies, migrations, reports, baselines, evaluation
outputs, live API calls, benchmarks, commits, pushes, resets, cleans, stashes,
discards, or overwrites were performed.

**STOP CONDITION:** This document is the only deliverable. Wait for explicit
approval.

