# Coraxis Researcher Two-Protocol Implementation Plan V3

## 1. Scope and approval boundary

This is the final safety-review revision of the approved V2 architecture.
It is planning-only. It does not modify application code, tests, dependency
manifests, migrations, benchmark outputs, existing reports, or baseline data.

The approved architecture remains:

1. **Protocol A:** a native-tool Researcher kickoff.
2. **Protocol B:** a separate no-tools formatter kickoff using
   `SubQuestions`.
3. Downstream Web Searcher, Analyst, and Report Writer tasks receive only
   their explicit immediate-predecessor outputs.

This revision resolves three safety gaps:

- the tool-result ledger is now registered before execution and is conservative
  about unresolved side effects;
- memory-first behavior is enforced programmatically, not only by prompting;
- collaboration state is captured through one atomic channel snapshot at the
  Protocol A completion boundary.

## 2. Preserved V2 decisions

| Decision | Final choice |
|---|---|
| Overall design | Option A |
| Orchestration | Two Coraxis-controlled CrewAI kickoffs |
| Initial rollout | Groq-only built-in Researcher pipeline |
| Non-Groq behavior | Existing single-stage behavior unchanged |
| Custom teams | Existing custom-team behavior unchanged |
| Protocol B | No native tools, `output_json=SubQuestions` |
| Handoff limit | 65,536 UTF-8 bytes |
| Downstream context | Explicit immediate-predecessor task contexts |
| Protocol B retries | Formatter-only, same immutable snapshot, maximum two retries |
| Dependencies | No dependency changes |
| Persistence | Existing run/event/stats persistence, no migration |
| Adapter | Existing Groq cache-marker adapter remains unchanged |

The in-memory ledger does **not** provide exactly-once execution. It provides
conservative retry protection while the process remains alive. A process crash
can lose the in-memory ledger; recovery must therefore fail or require a new
run rather than assume that an action did not occur.

## 3. Current implementation facts

### 3.1 Tool and context ownership

[`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py)
currently creates one `ToolContext` per run and shares its `AgentChannel` among
agent-specific context views. It has no general tool-result ledger today.

[`src/coraxis/agents/tools/crew_tools.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tools/crew_tools.py)
currently returns JSON strings directly to CrewAI. The six relevant tools are:

- `web_search`
- `recall_memory`
- `send_message`
- `read_inbox`
- `blackboard_write`
- `blackboard_read`

### 3.2 Collaboration state

[`src/coraxis/agents/comms.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/comms.py)
currently protects messages and blackboard entries with one `threading.RLock`.
Its `transcript()` and `entries()` methods each take a separate lock, so
calling them independently does not provide one consistent cross-structure
snapshot.

### 3.3 CrewAI context

CrewAI 1.15.37 aggregates prior raw task outputs when `Task.context` is
omitted. Explicit `context=[formatter_task]` aggregates only that task's raw
output. The implementation must use explicit contexts and must not use private
executor messages as a handoff contract.

## 4. Side-effect action ledger

### 4.1 Collector state and lifecycle

Add one `ToolResultCollector` to each run's `ToolContext`. `for_agent()` must
share the collector object while preserving the current run ID and changing
only agent attribution.

Every invocation follows this exact lifecycle:

```text
reserve sequence
  -> register STARTED record
  -> execute operation
  -> finalize SUCCEEDED, FAILED, or UNKNOWN
  -> record sanitized result/status
```

The sequence is reserved and the `STARTED` record is inserted **before** the
tool operation begins. No tool may execute before successful registration.

If registration fails, the operation must not start and Protocol A fails as a
collector failure.

If the operation starts but control is lost before finalization, the action is
`UNKNOWN`. An unknown side-effecting action makes Protocol A non-retryable.

If the operation succeeds but result sanitization or ledger finalization fails,
the operation is treated as unsafe: the record remains `UNKNOWN` or
`completion_unrecorded`, and Protocol A cannot automatically retry. The system
must never convert an unrecorded success into a safe failure.

### 4.2 Record structure

The exact implementation may use frozen dataclasses or Pydantic models, but
the following fields are required:

```python
ToolActionRecord:
    seq: int
    run_id: str
    agent_slug: str
    tool: ToolName
    side_effect: bool
    retry_class: Literal["read_only", "side_effecting"]
    status: Literal["started", "succeeded", "failed", "unknown"]
    started_at: float
    finished_at: float | None
    input_summary: Mapping[str, JSONValue]
    result_summary: Mapping[str, JSONValue]
    error_code: str
    completion_recorded: bool
```

`seq` is collector-local and monotonic. It is not a provider request ID and
does not claim exactly-once execution. `run_id` is assigned by Coraxis and
cannot be supplied by the model.

The collector also maintains guarded state:

```text
accepting_actions: bool
in_flight_count: int
frozen: bool
memory_policy: enabled|disabled
memory_first_state: pending|satisfied|failed|not_required
```

All state transitions occur under the collector lock or through a condition
variable associated with that lock.

### 4.3 Action classification

| Tool | Class | Side effect |
|---|---|---:|
| `web_search` | read-only | No Coraxis mutation |
| `recall_memory` | read-only | No Coraxis mutation |
| `read_inbox` | read-only | No mutation |
| `blackboard_read` | read-only | No mutation |
| `send_message` | side-effecting | Appends collaboration message |
| `blackboard_write` | side-effecting | Mutates blackboard |

`web_search` may return different external results on retry, but it does not
perform a Coraxis side effect. It is therefore retryable under the read-only
policy, with each attempt recorded separately.

### 4.4 Invocation API

All six tools must call a common collector/context boundary before their
operation. The intended interface is conceptually:

```python
action = context.begin_tool_action(
    tool="recall_memory",
    input_summary=...,
    side_effect=False,
)
try:
    value = await operation()
except CancelledError:
    context.unknown_tool_action(action, error_code="cancelled")
    raise
except Exception as exc:
    context.fail_tool_action(action, error_code=classify_error(exc))
    raise
else:
    try:
        result = sanitize_tool_result(tool, value)
        context.succeed_tool_action(action, result)
    except Exception:
        context.unknown_tool_action(
            action,
            error_code="result_recording_failed",
        )
        raise UnsafeToolLedgerError
```

The actual repository error type and async/sync bridge may differ, but the
ordering is mandatory. The normal CrewAI return string is preserved only after
the ledger has successfully recorded the result.

### 4.5 Retry-controller detection

The retry controller derives its decision from the ledger, not from the raw
LLM response:

```text
completed side effect:
    any side_effect=True record with status=succeeded

attempted unresolved side effect:
    any side_effect=True record with status in {started, unknown}
    or completion_recorded=False

read-only activity:
    records exist, but every record has side_effect=False
    and status in {succeeded, failed}

collector failure:
    registration failure, freeze failure, result-recording failure,
    sequence corruption, or snapshot inconsistency
```

The retry decision is:

| Ledger state | Protocol A automatic retry |
|---|---|
| No action attempted; provider failure | Allowed once |
| Read-only actions only, all finalized | Allowed once |
| Completed side effect present | Forbidden |
| Side effect started/unknown/unrecorded | Forbidden |
| Collector failure | Forbidden |
| Freeze or snapshot failure | Forbidden |
| Cancellation/deadline | Forbidden |

No automatic Protocol A retry is permitted if a side-effecting action was
attempted, even when its final status is unknown.

### 4.6 Interruption handling

At cancellation, timeout, thread failure, or process-level exception:

1. mark every still-started action as `unknown` where the process can still
   acquire the collector lock;
2. mark unresolved side-effecting actions as unsafe;
3. prevent any retry;
4. emit a redacted stage failure;
5. finalize the run as failed, cancelled, or timed out according to the
   existing run lifecycle.

If the process terminates before this cleanup executes, no durable claim is
made about action status. A restarted process must not replay Protocol A inside
the old run.

### 4.7 Deterministic ledger tests

The implementation must include tests for:

1. sequence reservation and `started` registration occur before the operation
   callback is entered;
2. operation success finalizes `succeeded`;
3. operation exception finalizes `failed`;
4. exception after operation but before result recording becomes `unknown`;
5. collector registration failure prevents operation execution;
6. timeout between registration and operation marks the action unknown;
7. timeout during operation marks a side-effecting action unknown;
8. exception during result sanitization makes the run unsafe to retry;
9. a completed side effect blocks Protocol A retry;
10. a started/unknown side effect blocks Protocol A retry;
11. finalized read-only failures permit the bounded retry policy;
12. collector freeze rejects later action registration;
13. two runs have independent sequences and ledgers;
14. tests do not assert exactly-once behavior.

## 5. Programmatic memory-first enforcement

### 5.1 Policy

When semantic memory is enabled, `recall_memory` must be the first
Researcher tool action. This is a runtime invariant, not merely an LLM
instruction.

When semantic memory is disabled:

- `recall_memory` is not required;
- a call to `recall_memory` may return the existing disabled response;
- the first action may be any permitted Researcher tool.

### 5.2 Enforcement location

Enforcement belongs in the guarded `ToolContext`/collector action-registration
boundary, not only in the orchestrator and not only in the registry:

- the orchestrator supplies `memory_enabled` when creating the run context;
- the collector tracks whether the first Researcher action has occurred;
- `begin_tool_action()` rejects any first Researcher action other than
  `recall_memory` when memory is enabled;
- the tool registry remains the source of tool construction and permissions;
- the orchestrator verifies the final ledger invariant before handoff.

This prevents a model from bypassing the rule and prevents an operation from
starting before the violation is detected.

### 5.3 State machine

Enabled memory:

```text
pending
  -- begin recall_memory --> in-flight
  -- any other begin --> reject, violation
  -- recall succeeds --> satisfied
  -- recall fails --> failed
  -- recall unknown --> failed/unsafe according to ledger
```

Disabled memory:

```text
not_required
  -- any permitted first action --> normal action lifecycle
```

The collector records the failed recall outcome explicitly. It must not
invent an empty successful memory result. A failed read-only recall does not
create a side effect; it may be reported to the model as unavailable and the
stage may continue once the first-action invariant is satisfied. An unknown
recall outcome is conservative: stop the stage if the collector cannot
finalize it.

### 5.4 Completion verification

At Protocol A completion, the orchestrator verifies:

```text
memory disabled:
    memory_first_state == not_required

memory enabled:
    first Researcher action exists
    first Researcher action.tool == recall_memory
    memory_first_state in {satisfied, failed}
```

If memory is enabled and no tool action occurred, or another tool action
occurred first, Protocol A fails safely. It must not repeat the stage because
the failure may follow an already attempted side effect. If a violation was
rejected before operation start, no side effect was created by that rejected
call, but the stage still fails rather than silently continuing.

### 5.5 Memory-first tests

Required deterministic tests:

1. enabled memory accepts `recall_memory` as the first action;
2. enabled memory rejects `web_search` as the first action before execution;
3. enabled memory rejects `send_message` as the first action before execution;
4. enabled memory rejects `read_inbox` and `blackboard_read` as first actions;
5. enabled memory with no tool invocation fails completion verification;
6. disabled memory permits any valid first action;
7. disabled memory does not require a fabricated recall result;
8. recall failure is recorded as failed and never represented as success;
9. recall unknown prevents unsafe continuation/retry;
10. a rejected ordering cannot trigger a side effect;
11. a later side effect after a successful/failed recall is handled normally;
12. concurrent runs enforce memory-first independently.

## 6. Atomic collaboration snapshot and handoff freeze

### 6.1 Required channel API

The existing `AgentChannel` lock protects each method independently, but
Protocol A needs one consistent view of messages and blackboard entries.
During implementation, add one method conceptually equivalent to:

```python
channel.snapshot() -> CollaborationSnapshot

CollaborationSnapshot:
    version: int
    messages: tuple[Mapping[str, JSONValue], ...]
    blackboard: tuple[Mapping[str, JSONValue], ...]
```

The method must acquire the existing `RLock` once, copy both collections while
holding it, and release the lock only after both copies and the version marker
are captured.

Every mutating `send()`, `post()`, and `clear()` operation increments a
channel-local version under the same lock. The snapshot's `version` is a
consistent marker for both structures. It is not a global event sequence and
does not claim cross-process durability.

`transcript()` and `entries()` may remain for existing callers, but the
handoff builder must not call them separately.

### 6.2 Snapshot consistency

The atomic snapshot must return:

- collaboration messages in deterministic insertion order;
- blackboard entries in deterministic timestamp/key order;
- one version marker captured under the same lock.

Values must be copied and sanitized before being placed in the immutable
handoff. The snapshot must not hold live mutable references to channel state.

### 6.3 Protocol A completion barrier

Protocol A completion is a barrier, not merely receipt of `TaskOutput.raw`:

1. Set `collector.accepting_actions = False` and `channel.accepting_mutations = False`
   under their respective locks.
2. Wait for in-flight tool calls to finish, using a bounded deadline.
3. If an in-flight call cannot finish, mark it `unknown` where possible.
4. If any unresolved side-effecting call remains, fail conservatively and do
   not build a successful handoff.
5. Freeze collector records.
6. Take exactly one atomic `channel.snapshot()`.
7. Sanitize and build the immutable `ResearcherHandoff`.
8. Validate the 65,536-byte limit and secret policy.
9. Store the handoff digest and prevent all later mutation.

The order must prevent a new tool action or collaboration mutation from
appearing after the snapshot boundary. The collector and channel need a
coordinated close protocol so a tool cannot pass one gate and mutate the other
after freezing.

The implementation should use a shared run-level completion barrier or a
strict lock ordering documented in code. It must not acquire collector and
channel locks in inconsistent orders.

### 6.4 Immutable handoff

The handoff is a frozen, versioned value:

```python
ResearcherHandoff:
    version: Literal["researcher-handoff-v1"]
    run_id: str
    query: str
    protocol_a_raw: str
    tool_results: tuple[FrozenToolActionRecord, ...]
    collaboration: CollaborationSnapshot
    completed_actions: tuple[str, ...]
    truncation: Mapping[str, JSONValue]
    digest: str
```

Nested mappings must be copied into immutable or no-alias representations.
Changing the collector, channel, or original tool return after construction
must not change the handoff or its digest.

### 6.5 Atomic snapshot tests

Required concurrent tests:

1. a writer cannot produce a snapshot containing a message from after the
   captured channel version;
2. a blackboard update concurrent with snapshot is either wholly before or
   wholly after the snapshot;
3. messages and blackboard entries come from one version marker;
4. mutation attempts after the freeze barrier are rejected;
5. in-flight read-only completion is awaited before successful freeze;
6. in-flight side-effect timeout yields unknown and blocks handoff/retry;
7. handoff mutation after construction cannot alter its digest;
8. two concurrent runs have disjoint channels, collectors, snapshots, and
   digests;
9. `snapshot()` is used instead of separate `transcript()`/`entries()` calls;
10. process interruption is documented as losing in-memory ledger state, not
    as proving actions were not executed.

## 7. Protocol A design and retry matrix

### 7.1 Protocol A

Kickoff 1 contains one native-tool Researcher task:

- existing Researcher tools remain available;
- no `output_json`;
- no `output_pydantic`;
- no JSON response format;
- concise raw handoff narrative;
- memory-first prompt remains helpful but is not the enforcement mechanism.

No Researcher tool other than `recall_memory` is mandatory when memory is
enabled. Web search remains optional because Web Searcher owns source
discovery.

### 7.2 Final retry matrix

| Condition | Side effect attempted? | Automatic Protocol A retry? | Required action |
|---|---:|---:|---|
| Provider failure before first action | No | Yes, once | Fresh Protocol A task |
| Final raw response invalid, no actions | No | Yes, once | Stricter raw-output instruction |
| Only finalized read-only actions | No | Yes, once | Fresh task; record new attempt |
| Recall failed, finalized | No | At most one under read-only rule | Do not invent memory success |
| Recall unknown | No, but unresolved read | No | Fail conservatively |
| `send_message` succeeded | Yes | No | Fail or require whole-run retry |
| `blackboard_write` succeeded | Yes | No | Fail or require whole-run retry |
| Side effect status `started` | Yes/possible | No | Mark unknown and fail |
| Side effect status `unknown` | Yes/possible | No | Fail conservatively |
| Result recording failed after operation | Unknown | No | Mark unsafe and fail |
| Collector registration failed | Operation must not start | No | Fail collector path |
| Freeze/snapshot failed | Possibly | No | Fail; no handoff |
| Cancellation/deadline | Possibly | No | Terminal cancel/timeout |
| Process interruption | Unknown | No in old run | New user retry creates a new run |

The whole-run retry endpoint may create a new run under existing semantics.
It must not claim that side effects from the old process did not occur.

## 8. Protocol B and downstream isolation

Kickoff 2 contains:

```text
formatter_task
  -> search_task(context=[formatter_task])
  -> analyse_task(context=[search_task])
  -> report_task(context=[analyse_task])
```

The formatter has zero tools and `output_json=SubQuestions`. It receives only
the serialized immutable handoff and original query. The validated
`SubQuestions` result is the only context passed to Web Searcher.

Web Searcher must not receive Protocol A raw prose, the collector ledger, the
full handoff envelope, or implicit prior kickoff output. Explicit contexts
must be tested by inspecting the constructed tasks and by a spy executor that
captures the actual context string.

Protocol B may retry the formatter at most twice. Each retry:

1. uses the exact same handoff object and digest;
2. creates a fresh no-tools formatter task/agent;
3. never calls Protocol A tools;
4. fails the run after the retry cap;
5. never substitutes an unvalidated or empty `SubQuestions`.

Web Searcher does not start until explicit `SubQuestions.model_validate(...)`
and `is_usable` validation succeeds.

## 9. Events, persistence, cancellation, and SSE

Use existing event types from
[`src/coraxis/db/enums.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/db/enums.py)
with redacted payload metadata:

```json
{
  "protocol": "A|B",
  "stage": "native_tools|handoff|structured_output",
  "attempt": 1,
  "action_seq": 12
}
```

Required order:

```text
run.started
agent.started(researcher, protocol=A)
tool.started / tool.completed-or-failed
agent.progress(handoff frozen)
agent.completed(researcher, protocol=A)
agent.started(researcher, protocol=B)
agent.completed(researcher, protocol=B)
agent.started(web_searcher)
...
report.ready
run.succeeded
```

If an action is unresolved, emit a redacted failure/unknown event and then the
existing terminal run event. Events continue through `EventRecorder`, which
persists before broadcasting; SSE replay therefore remains sequence-safe.

Persist only bounded operational stats in the existing run stats JSON:

```json
{
  "researcher_protocol": "two_protocol",
  "protocol_a_attempts": 1,
  "protocol_b_attempts": 1,
  "action_counts": {
    "started": 2,
    "succeeded": 1,
    "failed": 1,
    "unknown": 0
  },
  "side_effects_completed": 0,
  "side_effects_unresolved": 0,
  "handoff_bytes": 18432,
  "handoff_truncated": false,
  "handoff_digest": "<digest>",
  "token_usage": {
    "protocol_a": "N/A or measured",
    "protocol_b": "N/A or measured"
  }
}
```

Do not persist full handoffs, raw prompts, credentials, headers, unrestricted
tool arguments, or private CrewAI messages.

Before each stage and before handoff freezing, check the existing stop signal.
Cancellation or timeout must close action acceptance, resolve/mark in-flight
records, stop later stages, flush events, and write a terminal run state.

## 10. Provider and custom-agent boundaries

The two-protocol path is selected only for the built-in four-agent pipeline
when the Researcher provider is Groq and the configured model is the approved
GPT-OSS model. The exact gate must be explicit and observable.

Non-Groq providers retain their current single-Crew behavior. Custom providers
are not treated as Groq merely because they expose an OpenAI-compatible API.

`build_team_crew()` and arbitrary custom teams remain unchanged. A custom agent
with slug `researcher` is not transformed unless the run is the recognized
built-in pipeline.

## 11. Exact implementation and verification sequence

### Stage 0 — Contract and gate tests

Expected files:

- existing task/crew test locations;
- new focused two-protocol test module.

Tests:

- `SubQuestions` serialization/usability unchanged;
- Groq built-in gate selected;
- non-Groq and custom-team gates not selected;
- no dependency or migration changes.

### Stage 1 — Ledger and guarded action boundary

Expected files:

- [`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py);
- [`src/coraxis/agents/tools/crew_tools.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tools/crew_tools.py);
- focused collector tests.

Implement:

- pre-operation sequence reservation and `started` registration;
- success/failure/unknown finalization;
- side-effect classification;
- collector failure handling;
- retry decision API;
- memory-first guard;
- run-local ownership through `ToolContext.for_agent()`.

Tests must cover every lifecycle interruption listed in Sections 4 and 5.

### Stage 2 — Atomic channel snapshot and freeze barrier

Expected files:

- [`src/coraxis/agents/comms.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/comms.py);
- [`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py);
- snapshot/concurrency tests.

Implement:

- channel version marker;
- one lock-held `snapshot()` returning messages and blackboard;
- mutation rejection after freeze;
- coordinated collector/channel completion barrier;
- immutable handoff construction and digest.

Tests must prove version consistency, no post-freeze mutations, no cross-run
leaks, bounded UTF-8 size, redaction, and digest immutability.

### Stage 3 — Protocol A builder

Expected files:

- [`src/coraxis/agents/tasks.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tasks.py);
- [`src/coraxis/agents/crew.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/crew.py).

Implement the raw tool task and single-task kickoff builder. It must not
declare structured output. Test tool declarations, no JSON mode, and required
memory-first instructions.

### Stage 4 — Protocol B and explicit contexts

Expected files:

- [`src/coraxis/agents/tasks.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tasks.py);
- [`src/coraxis/agents/crew.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/crew.py).

Implement the no-tools formatter and second kickoff:

```text
formatter -> search(context=[formatter])
          -> analyse(context=[search])
          -> report(context=[analyse])
```

Test that actual Web Searcher context contains only validated formatter output
and that invalid formatter output prevents downstream execution.

### Stage 5 — Orchestrator integration

Expected files:

- [`src/coraxis/services/research.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/services/research.py);
- focused research/event/persistence tests.

Implement:

- Groq built-in gate;
- kickoff 1 and completion barrier;
- handoff creation;
- kickoff 2 and formatter-only retries;
- cancellation/timeout checks between stages;
- event ordering and bounded stats;
- unchanged final report/source/claim/memory persistence.

### Stage 6 — Adapter regression

Expected file:

- [`tests/unit/test_groq_compatibility.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/tests/unit/test_groq_compatibility.py)
  or the repository's actual test location.

Verify the existing adapter removes only `cache_breakpoint`, preserves
Protocol A tools, and leaves Protocol B tools-free. Do not change the adapter
without a separate proven regression.

### Stage 7 — Isolated live diagnostics

Use the isolated temporary environment and configured credential without
printing or persisting it:

1. Protocol A with the configured Groq model;
2. memory-first success and recall-failure diagnostics;
3. Protocol B with the captured handoff;
4. formatter validation retry using the same snapshot digest;
5. one controlled end-to-end four-agent pipeline case;
6. async execution, cancellation boundary, persistence, and SSE replay;
7. concurrent run isolation.

Do not run the ten-case benchmark in this stage.

## 12. Rollback criteria

Disable the two-protocol gate and return to the prior path if:

- any side-effecting action is retried automatically;
- an unresolved side effect is classified as safe;
- result recording fails but the operation is treated as failed/safe;
- memory-first is bypassed or a fake memory success is created;
- a post-freeze tool or collaboration mutation changes the handoff;
- the channel snapshot combines different versions;
- handoff or collector data crosses run boundaries;
- Protocol B receives native tools;
- Web Searcher receives Protocol A raw output unexpectedly;
- event persistence/SSE replay loses ordering;
- cancellation leaves a nonterminal run;
- non-Groq or custom-team behavior changes;
- `SubQuestions` or downstream API contracts change;
- secrets appear in logs, events, stats, diagnostics, or reports;
- a controlled Groq run still produces an undeclared `json`/`JSON` tool call.

Rollback is a code/provider-gate selection change. It must not use reset, clean,
stash, discard, or migration reversal.

## 13. Conditions before the ten-case benchmark

All conditions must pass before Phase 02F is rerun:

- [ ] Every tool invocation registers `started` before operation execution.
- [ ] Success, failure, and unknown lifecycle tests pass.
- [ ] Result-recording failure is unsafe and blocks Protocol A retry.
- [ ] Any attempted side effect blocks automatic Protocol A retry.
- [ ] Memory-first is enforced programmatically when enabled.
- [ ] Disabled-memory behavior is separately tested.
- [ ] Recall failure never becomes an invented success.
- [ ] Atomic channel snapshot returns one consistent version marker.
- [ ] Protocol A freezes action and collaboration mutation before handoff.
- [ ] In-flight unresolved side effects fail conservatively.
- [ ] Handoff is immutable, redacted, run-local, and <= 65,536 UTF-8 bytes.
- [ ] Protocol A contains native tools but no structured output configuration.
- [ ] Protocol B contains no native tools and returns validated `SubQuestions`.
- [ ] Web Searcher context is explicitly `[formatter_task]`.
- [ ] Protocol B retries reuse the exact same snapshot and never rerun tools.
- [ ] Events persist before SSE broadcast and replay in order.
- [ ] Cancellation and timeout tests pass at both kickoff boundaries.
- [ ] Token/retry/action statistics distinguish measured values from `N/A`.
- [ ] Non-Groq and custom-team behavior remains unchanged.
- [ ] Existing Groq adapter tests pass.
- [ ] One controlled live four-agent Groq run succeeds.
- [ ] Search, fetch, citation, report, memory, and persistence paths succeed.
- [ ] No undeclared `json`/`JSON` tool call occurs.
- [ ] Baseline and prior evaluation outputs remain unchanged.
- [ ] No secrets appear in outputs.

## 14. Exact expected implementation files

Expected production changes:

- [`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py)
  — collector ownership, guarded action lifecycle, memory-first state, freeze,
  and handoff creation.
- [`src/coraxis/agents/tools/crew_tools.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tools/crew_tools.py)
  — pre/post ledger capture for the six Researcher tools.
- [`src/coraxis/agents/comms.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/comms.py)
  — atomic versioned collaboration snapshot and mutation freeze.
- [`src/coraxis/agents/tasks.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tasks.py)
  — raw Protocol A and no-tools Protocol B task builders plus explicit
  immediate-predecessor contexts.
- [`src/coraxis/agents/crew.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/crew.py)
  — two kickoff builders and Groq built-in-pipeline gate support.
- [`src/coraxis/services/research.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/services/research.py)
  — stage orchestration, completion barrier, retry decisions, cancellation,
  events, and stats.

Expected tests:

- collector/lifecycle and memory-first tests;
- atomic channel/concurrency tests;
- task/crew context-isolation tests;
- research/event/persistence tests;
- existing Groq adapter regression tests.

Not expected to change:

- dependency manifests or lockfiles;
- database migrations;
- [`src/coraxis/services/llm/groq_compat.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/services/llm/groq_compat.py)
  unless a separate adapter regression is proven;
- `SubQuestions` fields;
- custom-team semantics;
- Phase 02A–02F reports and baseline data.

## 15. Final safety summary

### Decisions made

- Every action is registered before operation execution.
- The four ledger statuses are `started`, `succeeded`, `failed`, and `unknown`.
- Any attempted side effect, including unresolved/unknown side effects, blocks
  automatic Protocol A retry.
- A result-recording failure is unsafe.
- Memory-first is enforced by the guarded `ToolContext`/collector boundary and
  verified by the orchestrator.
- Collaboration state is captured by one lock-held, versioned channel snapshot.
- Protocol A freezes action and collaboration mutation before handoff creation.
- The handoff is immutable, redacted, run-local, digest-bound, and capped at
  65,536 UTF-8 bytes.
- All V2 architecture and compatibility decisions remain in force.

### Remaining risks

- The in-memory ledger cannot survive process death and does not provide
  exactly-once execution.
- A provider timeout after a side-effect request is inherently ambiguous;
  conservative failure is required.
- Two kickoffs increase latency and token cost.
- Tool results and collaboration content require strict redaction tests.
- CrewAI and the existing private cache-marker adapter require regression tests
  on every upgrade.

### Exact implementation files

`context.py`, `crew_tools.py`, `comms.py`, `tasks.py`, `crew.py`, and
`services/research.py`, plus focused tests. No dependencies, migrations,
baseline data, benchmark outputs, or existing reports should change.

**STOP CONDITION:** This V3 document is the only deliverable. No implementation
or benchmark execution is authorized by this plan.

