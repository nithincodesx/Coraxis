# Coraxis Researcher Two-Protocol Implementation Plan V4

## 1. Scope and preserved architecture

This is a planning-only safety clarification of V3. It does not modify
application code, tests, dependencies, migrations, benchmark outputs, reports,
baseline data, or external contracts.

All approved V3 decisions remain unchanged:

- two Coraxis-controlled CrewAI kickoffs;
- Groq-only built-in Researcher rollout;
- unchanged non-Groq and custom-team behavior;
- Protocol A with native tools and no structured output;
- Protocol B as a no-tools formatter using `output_json=SubQuestions`;
- explicit immediate-predecessor task contexts;
- a redacted, immutable, run-local handoff capped at 65,536 UTF-8 bytes;
- unchanged Groq cache-marker adapter;
- no dependency changes or database migrations;
- no ten-case benchmark until every implementation gate passes.

V4 clarifies:

1. one implementable run-level synchronization protocol for action admission,
   collaboration mutation, in-flight tracking, and handoff freezing;
2. independent memory-first enforcement for every fresh Protocol A attempt.

The in-memory ledger still does not provide exactly-once execution. It only
prevents unsafe automatic retries while the process and its ledger remain
alive. A process interruption can lose the ledger; the old run must then fail
conservatively or require a new user-initiated run.

## 2. Current code facts

[`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py)
creates one `ToolContext` per run and derives agent-specific views.

[`src/coraxis/agents/comms.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/comms.py)
currently uses an `RLock` around its message deque and blackboard. Its
`transcript()` and `entries()` methods are separate snapshots, so they are not
an atomic cross-structure handoff.

[`src/coraxis/agents/tools/crew_tools.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tools/crew_tools.py)
implements `web_search`, `recall_memory`, `send_message`, `read_inbox`,
`blackboard_write`, and `blackboard_read`. The first four relevant operations
return JSON strings to CrewAI; collaboration tools mutate the run-local
`AgentChannel`.

CrewAI 1.15.37 aggregates prior raw task outputs when `Task.context` is
omitted. The implementation must therefore keep
`context=[formatter_task]`, then `[search_task]`, then `[analyse_task]` in the
second kickoff.

## 3. One shared run-level coordination mechanism

### 3.1 `RunCoordination` ownership

Create one `RunCoordination` object per run. It is constructed by the
orchestrator and injected into both `ToolResultCollector` and `AgentChannel`.
`ToolContext` exposes the same object through every `for_agent()` view.

`RunCoordination` owns the sole synchronization authority:

```python
RunCoordination:
    lock: threading.RLock
    changed: threading.Condition(lock)
    accepting_actions: bool
    accepting_mutations: bool
    freeze_requested: bool
    frozen: bool
    in_flight_actions: int
    in_flight_by_seq: dict[int, ActionLease]
    attempt_counter: int
    cancellation_requested: bool
    deadline: float | None
```

The collector and channel may retain data structures, but their public
coordinated operations must not use independent locks. They must execute under
`coordination.lock`. This is intentional: separate collector and channel locks
alone cannot make action admission and channel mutation atomic.

The coordination object is run-local and never module-global. The run ID is
assigned by Coraxis and is not accepted from model tool arguments.

### 3.2 Lock ordering

There is exactly one required lock ordering:

```text
RunCoordination.lock
  -> collector state/data
  -> AgentChannel state/data
```

The implementation must not acquire a collector lock or channel lock
independently. Preferably, collector and channel coordinated state have no
additional locks at all. If an implementation retains private locks for
non-coordinated legacy methods, those methods must not be used by the
two-protocol path, and the documented order remains:

```text
coordination.lock -> collector.lock -> channel.lock
```

No code path may acquire `collector.lock` or `channel.lock` first. No code path
may acquire `channel.lock` and then `collector.lock`. The handoff builder,
freeze path, tool wrappers, `send_message`, and `blackboard_write` all enter
through `coordination.lock`, so reverse lock ordering is impossible by design.

### 3.3 Action lease

Every accepted tool invocation receives an `ActionLease`:

```python
ActionLease:
    seq: int
    attempt: int
    tool: ToolName
    side_effect: bool
    status: Literal["started", "succeeded", "failed", "unknown"]
    mutation_permitted: bool
```

The collector reserves a process-local monotonic `seq`, records `started`,
increments `in_flight_actions`, and stores the lease in
`in_flight_by_seq` while holding the coordination lock.

No operation starts before this admission succeeds.

## 4. Exact synchronization protocol

### 4.1 Normal read-only invocation

Read-only actions (`web_search`, `recall_memory`, `read_inbox`,
`blackboard_read`) use this sequence:

1. Acquire `coordination.lock`.
2. Check cancellation/deadline, `accepting_actions`, `frozen`, and
   per-attempt memory-first policy.
3. Reserve `seq`, register `started`, add the lease, increment
   `in_flight_actions`.
4. Release `coordination.lock`.
5. Execute the read-only operation.
6. Acquire `coordination.lock`.
7. Finalize `succeeded` or `failed` with a sanitized result/error.
8. Remove the lease, decrement `in_flight_actions`, notify
   `changed`, release the lock.

A read-only operation that cannot be finalized becomes `unknown`. It does not
permit a successful handoff until the action is finalized or the run is
failed conservatively. A finalized read-only failure may permit the bounded
Protocol A retry policy.

### 4.2 Normal side-effecting invocation

Side-effecting actions (`send_message`, `blackboard_write`) use the same
admission sequence, but their collaboration mutation is guarded by the same
coordination lock:

1. Acquire `coordination.lock`.
2. Check cancellation/deadline, action acceptance, freeze state, and
   memory-first policy.
3. Reserve `seq`, register `started`, add the lease, increment
   `in_flight_actions`.
4. Keep `coordination.lock` while performing the local channel mutation.
5. If the mutation succeeds, record the sanitized result as `succeeded`.
6. If the mutation raises, record `failed` if the outcome is known; otherwise
   record `unknown`.
7. Remove the lease, decrement `in_flight_actions`, notify `changed`.
8. Release `coordination.lock`.

These mutations are local, bounded operations. Holding the run lock across
them prevents the freeze path from taking a snapshot between action admission
and collaboration mutation. Side-effecting implementations must not perform
network or unbounded blocking work while holding this lock.

If a side-effecting operation is redesigned to include external I/O, split it
into an explicitly admitted external phase and a lock-guarded local mutation
phase. The local mutation must revalidate `accepting_mutations` before it
begins. If its outcome is ambiguous, mark `unknown` and block retry.

### 4.3 Freeze boundary

The freeze operation is owned by the orchestrator and uses the same
coordination lock:

1. Acquire `coordination.lock`.
2. Set `freeze_requested = True`, `accepting_actions = False`, and
   `accepting_mutations = False`.
3. New action admission fails immediately.
4. Wait on `changed` until `in_flight_actions == 0`, checking the deadline.
5. If every lease finalized safely, set `frozen = True`.
6. Copy collector records and call one lock-held `channel.snapshot_locked()`.
7. Release `coordination.lock` only after both copies and the channel version
   are captured.
8. Build and validate the immutable handoff from those copies.

No new action can begin after step 2. A side-effecting action that already
holds the lock completes before step 2 can acquire it. A side-effecting action
that was admitted but is waiting for its mutation permission observes
`accepting_mutations=False`, becomes `unknown`, and decrements the in-flight
count without mutating the channel.

A successful handoff is allowed only when:

```text
frozen == True
in_flight_actions == 0
no action has status started
no side-effecting action has status unknown
no collector failure occurred
channel snapshot was captured under the coordination lock
```

If a read-only action remains unresolved, the run also fails rather than
constructing a potentially incomplete handoff. No action may mutate the
channel after `frozen=True`.

### 4.4 Cancellation and timeout

**Waiting for admission:** cancellation/deadline causes admission to fail
before an action lease is created. The tool operation does not execute.

**Waiting for mutation permission:** the action lease already exists. The
action is marked `unknown` if mutation outcome cannot be established, the
in-flight count is decremented, and Protocol A is non-retryable if it is
side-effecting.

**Executing a read-only action:** cancellation or timeout requests shutdown;
the wrapper attempts to finalize `failed` or `unknown` under the coordination
lock. The action must finish or the run fails conservatively.

**Executing a side-effecting mutation:** because the local mutation is
coordination-lock guarded, freeze cannot interleave with it. If an exception
escapes before finalization, mark `unknown`; never retry automatically.

**Finalizing:** if the collector cannot record the result, status becomes
`unknown`/unrecorded and the run is unsafe. The operation must not be
reclassified as a safe failure.

## 5. Required pseudocode

### 5.1 Normal tool invocation

```text
invoke(tool, attempt, input):
    with coordination.lock:
        if cancelled_or_expired() or not accepting_actions or frozen:
            raise ActionRejected
        enforce_memory_first(tool, attempt)
        seq = collector.reserve_sequence()
        lease = collector.register_started(
            seq=seq,
            attempt=attempt,
            tool=tool,
            side_effect=policy(tool).side_effect,
            input_summary=sanitize_input(tool, input),
        )
        coordination.in_flight_actions += 1
        coordination.in_flight_by_seq[seq] = lease

        if lease.side_effect:
            if not accepting_mutations or freeze_requested:
                collector.finalize_unknown(seq, "mutation_rejected_after_freeze")
                remove_lease_and_notify(seq)
                raise ActionRejected
            try:
                result = perform_local_channel_mutation(tool, input)
                collector.finalize_succeeded(seq, sanitize_result(tool, result))
            except KnownOperationError as exc:
                collector.finalize_failed(seq, classify(exc))
                raise
            except BaseException:
                collector.finalize_unknown(seq, "side_effect_outcome_unknown")
                raise
            finally:
                remove_lease_and_notify(seq)
            return result

    try:
        result = perform_read_only_operation(tool, input)
    except KnownOperationError as exc:
        with coordination.lock:
            collector.finalize_failed(seq, classify(exc))
            remove_lease_and_notify(seq)
        raise
    except BaseException:
        with coordination.lock:
            collector.finalize_unknown(seq, "read_operation_outcome_unknown")
            remove_lease_and_notify(seq)
        raise
    else:
        with coordination.lock:
            try:
                collector.finalize_succeeded(seq, sanitize_result(tool, result))
            except BaseException:
                collector.finalize_unknown(seq, "result_recording_failed")
                raise UnsafeLedgerError
            finally:
                remove_lease_and_notify(seq)
        return result
```

The pseudocode's `finally` path must preserve the invariant that every
accepted lease is removed exactly once from the in-flight map, even though
execution itself is not exactly-once.

### 5.2 Successful completion barrier

```text
freeze_for_handoff(raw_output, query):
    with coordination.lock:
        coordination.freeze_requested = True
        coordination.accepting_actions = False
        coordination.accepting_mutations = False
        coordination.changed.notify_all()

        while coordination.in_flight_actions > 0:
            if deadline_expired():
                mark_started_actions_unknown()
                break
            coordination.changed.wait(timeout=remaining_deadline())

        if any_unresolved_or_unrecorded_action():
            coordination.frozen = True
            raise UnsafeHandoffError

        collector.freeze_locked()
        channel.freeze_locked()
        collaboration = channel.snapshot_locked()
        records = collector.copy_records_locked()
        coordination.frozen = True

    handoff = build_immutable_handoff(
        query=query,
        protocol_a_raw=raw_output,
        records=records,
        collaboration=collaboration,
    )
    validate_redaction_size_and_digest(handoff)
    return handoff
```

The collector and channel are frozen before their copies are released to the
handoff builder. The builder receives copied values, never live mutable
objects.

### 5.3 Timeout during an in-flight side effect

```text
timeout_during_side_effect(seq):
    with coordination.lock:
        coordination.cancellation_requested = True
        coordination.accepting_actions = False
        coordination.accepting_mutations = False
        coordination.freeze_requested = True

        lease = coordination.in_flight_by_seq.get(seq)
        if lease is not None and lease.status == "started":
            collector.finalize_unknown(seq, "timeout_side_effect")
            remove_lease_and_notify(seq)

        for other in started_leases():
            if operation_control_is_lost(other):
                collector.finalize_unknown(other.seq, "timeout_in_flight")
                remove_lease_and_notify(other.seq)

        coordination.frozen = True
        raise UnsafeSideEffectError
```

If the operation later returns after this timeout path, its late completion
must not overwrite `unknown` or mutate a frozen channel. The wrapper must
discard/flag the late result and emit a diagnostic; it must not claim safe
completion.

### 5.4 Rejected mutation after freeze

```text
send_message_or_blackboard_write(input):
    with coordination.lock:
        if (
            not coordination.accepting_actions
            or not coordination.accepting_mutations
            or coordination.freeze_requested
            or coordination.frozen
        ):
            raise ActionRejected("collaboration mutation closed")

        lease = collector.register_started_before_operation(...)
        coordination.in_flight_actions += 1
        try:
            result = channel.mutate_locked(input)
            collector.finalize_succeeded(lease.seq, sanitize(result))
            return result
        except BaseException:
            collector.finalize_unknown(lease.seq, "mutation_outcome_unknown")
            raise
        finally:
            remove_lease_and_notify(lease.seq)
```

An action rejected before registration has no tool side effect and is not a
completed action. It still fails the current Protocol A attempt because the
stage violated its closure boundary; it must not be silently retried if the
surrounding failure could have included another unresolved action.

## 6. Atomic `AgentChannel` snapshot

### 6.1 Channel API

Add a coordination-aware API conceptually equivalent to:

```python
channel.snapshot_locked() -> CollaborationSnapshot

CollaborationSnapshot:
    version: int
    messages: tuple[Mapping[str, JSONValue], ...]
    blackboard: tuple[Mapping[str, JSONValue], ...]
```

`snapshot_locked()` may only be called while holding
`RunCoordination.lock`. It copies both message and blackboard state in one
critical section and captures one channel-local version marker.

`send()` and `post()` increment that version under `RunCoordination.lock`.
After `channel.freeze_locked()`, both reject new mutations. Existing
read-only methods may remain for compatibility, but the handoff path must
never call `transcript()` and `entries()` separately.

### 6.2 Race proof

There are only three possible orderings:

1. A side-effect mutation acquires `coordination.lock` first. It registers,
   mutates, finalizes, and releases before freeze acquires the lock; the
   mutation is included in the snapshot.
2. Freeze acquires `coordination.lock` first. It closes admission and
   mutation, so a later mutation is rejected and absent from the snapshot.
3. A read-only action is executing without the lock. Freeze closes admission
   and waits for its lease; the action finalizes before successful snapshot,
   or becomes unknown and prevents handoff.

There is no fourth ordering in which an accepted side-effecting action can
mutate after the snapshot, because mutation and snapshot both require the same
coordination lock and mutation rechecks the freeze state.

## 7. Protocol A attempts and memory-first state

### 7.1 Attempt numbering

Each fresh Protocol A execution receives a monotonically increasing attempt
number:

```text
attempt 1, attempt 2, ...
```

The number is allocated by the orchestrator under `RunCoordination.lock`
before constructing the fresh Agent/Task. It is never reused, even if an
attempt fails before its first tool action.

Every `ToolActionRecord` contains both:

```text
attempt: int
seq: int
```

`seq` is globally monotonic within the run. `(attempt, seq)` uniquely
identifies an action in diagnostics. Statistics retain per-attempt action
counts and the global sequence range.

### 7.2 Independent memory-first state

Memory-first is checked independently for every fresh attempt. The collector
maintains:

```text
AttemptState:
    attempt: int
    memory_policy: enabled|disabled
    first_action_seq: int | None
    first_action_tool: ToolName | None
    memory_first_state: pending|satisfied|failed|not_required|violated
```

For each attempt:

- enabled memory starts in `pending`;
- the first admitted Researcher action must be `recall_memory`;
- any other first action is rejected before its operation executes and marks
  the attempt `violated`;
- a successful recall becomes `satisfied`;
- a recall exception becomes `failed`;
- an unresolved recall becomes `failed` plus unsafe for handoff/retry;
- disabled memory starts in `not_required` and does not require recall.

The first action check is performed inside `begin_tool_action()` while holding
`RunCoordination.lock`. The orchestrator verifies the same invariant at
attempt completion. Prompt instructions remain useful but are not the guard.

### 7.3 Failed recall and a permitted retry

A finalized failed `recall_memory` is retained as `status="failed"` with its
attempt number and error category. It is never converted into a successful
empty result.

Because `recall_memory` is read-only, a finalized failed recall may permit one
fresh Protocol A attempt, subject to all other retry rules. The next attempt:

1. receives the next attempt number;
2. resets its own memory-first state to `pending`;
3. requires `recall_memory` as its first action again;
4. records a new `(attempt, seq)` action;
5. never edits or replaces the failed action from the prior attempt.

A failed recall does not waive memory-first on the next attempt and does not
make the prior attempt's empty result appear successful.

### 7.4 Side effects across attempts

Any attempted side effect in any Protocol A attempt blocks all automatic
Protocol A retries for the run, including a retry that would otherwise be
allowed after a later read-only failure. This includes:

- `send_message` with `succeeded`;
- `send_message` with `started` or `unknown`;
- `blackboard_write` with `succeeded`;
- `blackboard_write` with `started` or `unknown`;
- result-recording failure after either side-effecting operation.

An unknown or unrecorded action outcome also blocks retry. The retry controller
examines the complete run ledger, not only the latest attempt.

### 7.5 Attempt diagnostics and statistics

The handoff diagnostics and run stats must include only bounded metadata:

```json
{
  "protocol_a_attempts": 2,
  "attempts": [
    {
      "attempt": 1,
      "first_action": {"seq": 1, "tool": "recall_memory"},
      "memory_first_state": "failed",
      "actions": {"succeeded": 0, "failed": 1, "unknown": 0},
      "side_effect_attempted": false
    },
    {
      "attempt": 2,
      "first_action": {"seq": 2, "tool": "recall_memory"},
      "memory_first_state": "satisfied",
      "actions": {"succeeded": 2, "failed": 0, "unknown": 0},
      "side_effect_attempted": false
    }
  ],
  "global_action_seq_range": [1, 2],
  "automatic_retry_allowed": false
}
```

Do not persist raw memory contents, prompts, credentials, headers, or private
CrewAI messages in diagnostics or stats.

## 8. Retry decision matrix across attempts

| Complete-run ledger condition | Next Protocol A attempt? | Reason |
|---|---:|---|
| Attempt 1 provider failure before any action | Yes, once | No operation could have occurred |
| Attempt 1 finalized read-only failure only | Yes, once | Read-only actions are replay-safe by policy |
| Attempt 1 failed recall only | Yes, once | New attempt must recall first again |
| Attempt 1 first action violated memory-first | No | Stage contract failed; do not silently continue |
| Attempt 1 completed side effect | No | Duplicate collaboration mutation risk |
| Attempt 1 unknown/unrecorded side effect | No | Outcome cannot be determined |
| Attempt 1 collector/freeze failure | No | Ledger or handoff safety is unproven |
| Attempt 2 begins with non-recall while memory enabled | No | Rejected before operation; attempt violated |
| Attempt 2 finalized read-only failure, no side effects in either attempt | No after retry cap | Bounded retry exhausted |
| Any side effect in attempt 2 | No | Complete-run ledger is non-retryable |
| Memory disabled in all attempts | Apply ordinary read-only/side-effect policy | No recall requirement |

Protocol B retries remain separate: they reuse the same immutable handoff,
never create Protocol A attempts, and never invoke Protocol A tools.

## 9. Required deterministic tests

### 9.1 Synchronization and race tests

1. Normal read-only action registers `started` before its callback runs.
2. Normal side-effect action registers before channel mutation.
3. Freeze closes action admission before waiting.
4. A side-effect action holding the coordination lock completes before freeze
   can snapshot.
5. An admitted side-effect action waiting for mutation permission is rejected
   after freeze and becomes `unknown` without mutating the channel.
6. A read-only action in flight is awaited before a successful snapshot.
7. A read-only action that cannot finalize blocks successful handoff.
8. An in-flight side-effect timeout becomes `unknown` and blocks retry.
9. A result-recording exception after operation blocks retry.
10. A post-freeze `send_message` is rejected and produces no channel entry.
11. A post-freeze `blackboard_write` is rejected and produces no entry.
12. Snapshot and mutation cannot acquire locks in reverse order.
13. Snapshot contains exactly one channel version for messages and blackboard.
14. Concurrent writers produce either pre-freeze or rejected post-freeze state.
15. Two concurrent runs cannot share coordination, ledgers, channels, or
    handoff digests.
16. A process-interruption simulation documents loss of in-memory knowledge and
    does not assert exactly-once execution.

### 9.2 Per-attempt memory-first and retry tests

1. Attempt 1 begins with `recall_memory` when memory is enabled.
2. A failed recall is recorded as failed, not successful or fabricated empty.
3. A permitted retry after failed recall is attempt 2 and begins with
   `recall_memory` again.
4. Attempt 2 cannot begin with `web_search` when memory is enabled.
5. Attempt 2 cannot begin with `send_message` or `blackboard_write` when memory
   is enabled.
6. A successful side effect in attempt 1 blocks retry into attempt 2.
7. An unknown side effect in attempt 1 blocks retry into attempt 2.
8. A successful side effect in attempt 2 blocks any later retry.
9. An unknown/unrecorded action in either attempt blocks retry.
10. Disabled memory permits any valid first tool in every attempt.
11. Missing invocation with enabled memory fails attempt completion.
12. Recall failure in attempt 1 does not alter attempt 2's fresh state.
13. Every action records both attempt number and global sequence.
14. Concurrent runs maintain independent attempt counters and memory-first state.

### 9.3 Context and downstream tests

1. Protocol A declares native tools but no structured output.
2. Protocol B formatter has zero tools and `SubQuestions`.
3. `search_task.context == [formatter_task]`.
4. Web Searcher receives validated formatter output only, not Protocol A raw
   output or the full handoff.
5. Analyst receives only `search_task`; Report Writer receives only
   `analyse_task`.
6. Invalid formatter output prevents Web Searcher execution.
7. Protocol B retry reuses one handoff digest and never changes the ledger.

## 10. Events, persistence, and SSE

Use existing event types and include bounded metadata:

```json
{
  "protocol": "A|B",
  "stage": "native_tools|handoff|structured_output",
  "attempt": 1,
  "action_seq": 7,
  "status": "started|succeeded|failed|unknown"
}
```

Events continue through `EventRecorder`, which persists before broadcasting.
The required ordering remains:

```text
run.started
agent.started(researcher, protocol=A)
tool.started / tool.finalized
agent.progress(handoff frozen)
agent.completed(researcher, protocol=A)
agent.started(researcher, protocol=B)
agent.completed(researcher, protocol=B)
agent.started(web_searcher)
...
run.succeeded
```

Persist bounded action/attempt counts, first-action metadata, retry decisions,
handoff byte count, and digest. Do not persist raw handoffs, memory contents,
credentials, headers, unrestricted tool arguments, or private executor
messages.

Cancellation and timeout close action admission, resolve or mark in-flight
leases, stop later stages, flush events, and write a terminal run state.

## 11. Provider, custom-agent, and rollback boundaries

The two-protocol gate applies only to the recognized built-in four-agent
pipeline with the configured Groq Researcher model. Non-Groq providers,
custom providers, custom agents, and custom teams retain their existing path.

Rollback is required if:

- any side-effect action is retried automatically;
- an unknown/unrecorded outcome is considered safe;
- a tool mutates collaboration after freeze;
- a snapshot combines different channel versions;
- memory-first is bypassed on any attempt;
- a failed recall is fabricated as success;
- attempt/sequence diagnostics are ambiguous;
- Protocol B receives native tools;
- downstream context leaks Protocol A output;
- event/SSE ordering or terminal status breaks;
- non-Groq/custom behavior changes;
- external contracts or `SubQuestions` change;
- secrets appear in outputs;
- controlled Groq execution still emits undeclared `json`/`JSON`.

Rollback is a provider/code-path selection change only. It must not use reset,
clean, stash, discard, or migration reversal.

## 12. Updated implementation sequence and expected files

### Stage 0 — Contract and gate tests

Lock `SubQuestions`, provider gating, custom-team behavior, and immediate
predecessor context expectations.

### Stage 1 — Run coordination and action ledger

Expected files:

- [`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py)
- [`src/coraxis/agents/tools/crew_tools.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tools/crew_tools.py)

Implement `RunCoordination`, pre-operation registration, in-flight leases,
four statuses, cancellation handling, and per-attempt memory-first admission.
Add lifecycle, race, and retry tests.

### Stage 2 — Channel snapshot and freeze

Expected files:

- [`src/coraxis/agents/comms.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/comms.py)
- [`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py)

Implement the coordination-aware versioned `snapshot_locked()`, mutation
freeze, one-lock handoff copy, and immutable digest. Add deterministic
concurrency tests.

### Stage 3 — Protocol A builder

Expected files:

- [`src/coraxis/agents/tasks.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tasks.py)
- [`src/coraxis/agents/crew.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/crew.py)

Build the native-tool raw task and single-task kickoff with no structured
output. Add tool-declaration and memory-first instruction tests.

### Stage 4 — Protocol B and explicit contexts

Expected files:

- [`src/coraxis/agents/tasks.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tasks.py)
- [`src/coraxis/agents/crew.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/crew.py)

Build the no-tools formatter and:

```text
formatter -> search(context=[formatter])
          -> analyse(context=[search])
          -> report(context=[analyse])
```

### Stage 5 — Orchestrator integration

Expected file:

- [`src/coraxis/services/research.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/services/research.py)

Integrate two kickoffs, attempt numbering, freeze barrier, handoff validation,
stage retries, events, cancellation, stats, and unchanged final persistence.

### Stage 6 — Adapter regression

Expected test location:

- [`tests/unit/test_groq_compatibility.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/tests/unit/test_groq_compatibility.py)

Verify the existing adapter removes only `cache_breakpoint`, preserves
Protocol A tools, and leaves Protocol B tools-free. Do not change the adapter
without a separate proven regression.

### Stage 7 — Isolated diagnostics

Use the isolated temporary environment without exposing credentials:

1. Protocol A and per-attempt memory-first behavior;
2. failed recall followed by permitted retry;
3. side-effect timeout and conservative failure;
4. Protocol B with the same handoff digest across retries;
5. one controlled end-to-end four-agent Groq run;
6. async, cancellation, persistence, SSE replay, and concurrent isolation.

Do not run the ten-case benchmark at this stage.

## 13. Benchmark readiness gates

Before the ten-case benchmark:

- [ ] One run-level coordination mechanism governs collector and channel.
- [ ] No reverse lock ordering is possible.
- [ ] Every action registers before operation.
- [ ] Started/succeeded/failed/unknown lifecycle tests pass.
- [ ] In-flight action count and freeze barrier race tests pass.
- [ ] No mutation begins after freeze.
- [ ] Unresolved side effects block all automatic Protocol A retry.
- [ ] Memory-first is enforced independently on every attempt.
- [ ] Failed recall is never fabricated as success.
- [ ] Attempt and global sequence metadata are unambiguous.
- [ ] Atomic channel snapshot/version tests pass.
- [ ] Handoff is immutable, redacted, run-local, and <= 65,536 bytes.
- [ ] Protocol A has native tools and no structured output.
- [ ] Protocol B has no native tools and valid `SubQuestions`.
- [ ] Explicit downstream contexts prevent raw handoff leakage.
- [ ] Protocol B retries reuse the same snapshot and never rerun Protocol A.
- [ ] Event persistence/SSE replay remains ordered and gap-free.
- [ ] Cancellation and timeout paths are terminal.
- [ ] Non-Groq/custom behavior is unchanged.
- [ ] Existing adapter tests pass.
- [ ] One controlled live four-agent Groq run succeeds.
- [ ] Search, fetch, citation, memory, report, and persistence paths succeed.
- [ ] No undeclared `json`/`JSON` call occurs.
- [ ] Baseline and prior outputs remain unchanged.

## 14. Final clarification summary

### Synchronization decision

Use one run-local `RunCoordination.lock` and condition variable as the sole
authority for action admission, in-flight accounting, side-effecting channel
mutation, freeze, and atomic channel snapshot. Read-only operations release the
lock while executing but retain an in-flight lease. Side-effecting local
mutations execute under the same lock as freeze. Freeze closes admission,
waits for leases, marks unresolved actions unknown, and permits a handoff only
when no unsafe action remains.

### Memory-first decision

Attempt numbers start at 1 and increase monotonically. Every fresh Protocol A
attempt independently requires `recall_memory` as its first action when memory
is enabled. A finalized failed recall permits one bounded fresh attempt only
when no side effect or unknown/unrecorded action exists; the next attempt
performs and records its own first recall. Any side effect in any attempt
blocks automatic retry for the complete run.

### Planning-only confirmation

V4 is a planning document only. No application source, tests, dependency
files, migrations, reports, baseline data, evaluation outputs, live API calls,
benchmarks, commits, pushes, resets, cleans, stashes, or discards were made.

**STOP CONDITION:** deliver this document and wait for explicit approval.

