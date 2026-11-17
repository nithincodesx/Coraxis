# Coraxis Researcher Two-Protocol Implementation Plan V2

## 1. Status and objective

This is an implementation-ready, planning-only revision. It does not modify
application code, dependencies, migrations, benchmark data, existing reports,
or the Phase 02A baseline.

The objective is to preserve the existing `SubQuestions` contract while
separating:

1. Researcher native-tool execution.
2. No-tools structured-output generation.

The known failure is the combination of Researcher native tools and
`output_json=SubQuestions` in CrewAI 1.15.37. With
`groq/openai/gpt-oss-120b`, the model can emit an undeclared `json`/`JSON` tool
call, which Groq rejects. The existing Groq adapter is not responsible for
this behavior and must remain limited to `cache_breakpoint` removal.

## 2. Decisions made

| Decision | Choice |
|---|---|
| Overall design | Option A: native-tool stage followed by no-tools structured stage |
| Orchestration | Two Coraxis-controlled CrewAI kickoffs |
| Initial rollout | Groq-only for the built-in Researcher path |
| Non-Groq behavior | Preserve the current single-stage path until equivalent regression coverage passes |
| Tool-result storage | A run-local `ToolResultCollector` owned by `ToolContext` |
| Handoff | Frozen, versioned, sanitized `ResearcherHandoff` snapshot |
| Maximum handoff | 64 KiB UTF-8 serialized payload |
| Downstream context | Explicit `context=[formatter_task]`; never implicit prior-task aggregation |
| Protocol A retries | Only before side effects, or after read-only actions; fail conservatively after side effects |
| Protocol B retries | Formatter-only, same immutable snapshot, maximum two retries |
| Required tool action | Attempt `recall_memory` first when memory is enabled; no other tool call is mandatory |
| Events | Existing `AGENT_*` and `TOOL_*` event types with `protocol`/`stage` payloads |
| Persistence | Existing run/event/stats persistence; no migration |
| Custom teams | Do not alter custom-team semantics in the first rollout |
| Benchmark gate | One controlled live four-agent run plus deterministic and isolation tests before Phase 02F rerun |

The two-kickoff decision is deliberate. A single sequential Crew is simpler,
but its task-level retry and accumulated task-output behavior make it harder to
retry Protocol B without rerunning Protocol A. Two kickoffs give Coraxis an
explicit immutable boundary and stage-specific retry policy.

## 3. Verified current architecture

### 3.1 Built-in pipeline

[`src/coraxis/agents/crew.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/crew.py)
currently builds one sequential Crew:

```text
Researcher -> Web Searcher -> Analyst -> Report Writer
```

[`src/coraxis/agents/tasks.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tasks.py)
currently gives the Researcher native tools and `output_json=SubQuestions` in
the same task. The Web Searcher, Analyst, and Report Writer also use structured
output models.

[`src/coraxis/services/research.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/services/research.py)
currently creates one `ToolContext`, one `EventRecorder`, one cancellation
watcher, and calls `crew.kickoff_async()`. Final sources, claims, report, and
memory are persisted after the Crew completes.

### 3.2 Tool and collaboration state

[`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py)
contains run-scoped dependencies, but currently does not retain a general
record of tool return values. `publish()` emits observability events only.

[`src/coraxis/agents/comms.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/comms.py)
provides a bounded, thread-safe `AgentChannel` containing:

- a message deque capped at 500 messages;
- a blackboard capped at 200 entries;
- `transcript()`, `entries()`, `inbox()`, and `read()` snapshots.

[`src/coraxis/agents/tools/crew_tools.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tools/crew_tools.py)
shows that tools return JSON strings to CrewAI:

- `SearchTool` returns query and search results;
- `RecallMemoryTool` returns topic and prior findings;
- `SendMessageTool` returns the sent message record;
- `ReadInboxTool` returns messages;
- `BlackboardWriteTool` returns key and stored status;
- `BlackboardReadTool` returns key and value when found.

The existing citation tracker remains the source of truth for discovered
sources and claims. The new collector is a separate handoff/operability
record; it must not replace citation tracking.

### 3.3 Verified CrewAI context semantics

CrewAI 1.15.37's public `Crew._get_context()` behavior was inspected in the
installed environment:

```python
if not task.context:
    return ""
return (
    aggregate_raw_outputs_from_task_outputs(task_outputs)
    if task.context is NOT_SPECIFIED
    else aggregate_raw_outputs_from_tasks(task.context)
)
```

Therefore:

- an omitted `context` aggregates prior task outputs;
- `context=[specific_task]` aggregates only the referenced task's raw output;
- `context=[]` is not a substitute for a meaningful handoff;
- `TaskOutput.messages` and private executor state must not be used as the
  application handoff contract.

This fact drives the explicit context design in Section 7.

## 4. Explicit per-run tool-result collection

### 4.1 Ownership and isolation

Add a collector instance to each `ToolContext`. It must be created in
`ResearchOrchestrator._drive()` and passed through `ToolContext.for_agent()`.
`for_agent()` must preserve the same collector object while changing only
`agent_slug`.

No module-level collector, global list, static cache, or shared mutable
snapshot is permitted. The existing `AgentChannel` remains run-local and is
shared only by agents in that run.

The collector is associated with a run by:

```text
ToolContext.run_id -> ToolResultCollector.run_id
```

Every record also stores the invoking `agent_slug` and a collector-local
monotonic sequence number. The run ID is metadata only; it is never accepted
from an LLM tool argument.

### 4.2 Exact internal structures

The implementation should use typed dataclasses or equivalent Pydantic models
with immutable snapshot output. The intended structures are:

```python
ToolName = Literal[
    "web_search",
    "recall_memory",
    "send_message",
    "read_inbox",
    "blackboard_write",
    "blackboard_read",
]

ToolResultRecord:
    seq: int
    run_id: str
    agent_slug: str
    tool: ToolName
    started_at: float
    finished_at: float
    status: Literal["succeeded", "failed", "cancelled"]
    side_effect: bool
    retry_safe: bool
    input_summary: Mapping[str, JSONValue]
    result_summary: Mapping[str, JSONValue]
    error_code: str

ResearcherHandoff:
    version: Literal["researcher-handoff-v1"]
    run_id: str
    query: str
    protocol_a_raw: str
    tool_results: tuple[ToolResultRecord, ...]
    collaboration_messages: tuple[Mapping[str, JSONValue], ...]
    blackboard_entries: tuple[Mapping[str, JSONValue], ...]
    completed_actions: tuple[str, ...]
    truncation: Mapping[str, JSONValue]
```

The actual type spelling may follow repository conventions, but these fields
and invariants are required:

- records are ordered by `seq`;
- snapshot fields are tuples or frozen equivalents;
- all maps are copied before snapshot creation;
- no record contains the original unbounded tool-return string;
- `completed_actions` uses deterministic action IDs based on collector
  sequence, not model-generated IDs.

Suggested policy metadata:

| Tool | Side effect | Retry-safe after success | Handoff result |
|---|---:|---:|---|
| `web_search` | No Coraxis side effect | Yes | query, bounded result metadata |
| `recall_memory` | No Coraxis side effect | Yes | bounded findings and status |
| `send_message` | Yes | No | recipient, bounded message digest/content |
| `read_inbox` | Read-only | Yes | bounded message records |
| `blackboard_write` | Yes | No | key, stored status, value digest |
| `blackboard_read` | Read-only | Yes | key, found flag, bounded value |

`web_search` is operationally repeatable but can produce different external
results. It is marked retry-safe for run control because it has no Coraxis
side effect; repeat results must still be recorded as separate attempts.

### 4.3 Capture point

Each listed tool must capture a sanitized record after its operation returns
and capture a failure record when the operation raises. The capture must happen
inside the tool implementation or a common `ContextTool` recording helper,
not by inspecting CrewAI executor messages.

The implementation sequence should:

1. reserve the collector sequence and start time;
2. sanitize the input allowlist;
3. execute the tool operation;
4. sanitize the returned value into the tool-specific result schema;
5. append an immutable record;
6. publish the existing progress event;
7. return the normal JSON string to CrewAI.

If sanitization or recording fails, the tool must log the failure through the
repository logger and fail the tool call explicitly. It must not silently
pretend that an unrecorded result was captured.

The collector must be thread-safe because CrewAI can invoke tool code from
worker threads. A lock protects sequence allocation and append operations.

### 4.4 Tool-specific safe summaries

The collector stores only allowlisted summaries:

#### `web_search`

```json
{
  "query": "<bounded query>",
  "result_count": 8,
  "results": [
    {"url": "<url>", "title": "<title>", "snippet": "<bounded snippet>"}
  ]
}
```

Do not store full page text, authorization headers, cookies, or raw HTTP
responses. Full source data remains in the existing citation/fetch path.

#### `recall_memory`

```json
{
  "topic": "<bounded topic>",
  "result_count": 5,
  "results": [
    {
      "claim": "<bounded claim>",
      "sources": ["<bounded URL list>"],
      "confidence": 0.0,
      "relevance": 0.0
    }
  ],
  "status": "enabled|disabled|failed"
}
```

Exclude vector IDs, embeddings, database rows, stack traces, and raw exception
text. A short error category may be recorded.

#### `send_message`

```json
{
  "to_agent": "<agent name>",
  "message": "<redacted, bounded message>",
  "message_digest": "<sha256 of pre-truncation message>"
}
```

The message is retained only because it is collaboration input. Redact
credential-like values, bearer tokens, API-key patterns, authorization
headers, and other configured secret forms before storage.

#### `read_inbox`

```json
{
  "message_count": 10,
  "messages": [
    {
      "from_agent": "<agent>",
      "to_agent": "<agent or all>",
      "message": "<redacted, bounded message>",
      "ts": 0.0
    }
  ]
}
```

#### `blackboard_write`

```json
{
  "key": "<bounded key>",
  "stored": true,
  "value_digest": "<sha256 of pre-truncation value>"
}
```

Do not copy the full arbitrary blackboard value into the collector record.
The immutable handoff may include a separately sanitized bounded value when it
is needed for the plan, as specified below.

#### `blackboard_read`

```json
{
  "key": "<bounded key>",
  "found": true,
  "value": "<redacted, bounded value>",
  "value_digest": "<sha256 of pre-truncation value>"
}
```

### 4.5 Handoff snapshot construction

At Protocol A completion, call a Coraxis-owned snapshot builder with:

```text
query
protocol_a_raw
collector.records()
channel.transcript()
channel.entries()
```

The builder:

1. copies records under the collector lock;
2. copies channel snapshots under the channel lock;
3. redacts secret-like text;
4. applies per-field limits;
5. applies the total 64 KiB serialized UTF-8 limit;
6. freezes the result into tuples and copied mappings;
7. records exact truncation counters and original/retained byte counts;
8. computes a stable snapshot digest for retry identity.

The snapshot must not include:

- API keys or credential values;
- authorization headers, cookies, or provider request headers;
- raw LiteLLM/CrewAI request objects;
- embeddings, vector-store internals, or database session objects;
- full fetched page text;
- unrestricted prompts or private executor messages;
- unredacted exception tracebacks.

### 4.6 Deterministic truncation

The total serialized handoff limit is **65,536 UTF-8 bytes**. The builder
serializes with sorted keys, compact separators, UTF-8, and no ASCII escaping
unless required by the repository serializer.

Per-field limits:

- `protocol_a_raw`: 16,384 bytes;
- each tool result: 4,096 bytes;
- each collaboration message: 1,024 bytes;
- each blackboard entry: 1,024 bytes;
- query and scalar metadata: 4,096 bytes combined.

If the total exceeds 65,536 bytes, retain data in this order:

1. query and metadata;
2. required memory status/result summary;
3. tool records by ascending sequence;
4. collaboration messages by ascending source sequence;
5. blackboard entries by ascending timestamp;
6. Protocol A raw output last.

Within a field, truncate at a UTF-8-safe boundary and append a
`truncated=true` marker. Never silently drop a record. If the minimum envelope
cannot fit, fail Protocol A handoff explicitly.

The formatter is instructed to treat omitted/truncated data as unavailable,
not to infer it.

## 5. Protocol A design and retry policy

### 5.1 Crew shape

Kickoff 1 contains one CrewAI task:

```text
Researcher native-tool agent
  -> raw Protocol A task
```

The task has the existing Researcher tools, no `output_json`, no
`output_pydantic`, and no JSON response-format request. Its expected output is
plain bounded prose describing the decomposition facts, not a JSON tool call.

The task must explicitly instruct:

- call `recall_memory` first when memory is enabled;
- use collaboration tools when useful;
- do not claim a tool result that was not returned;
- finish with a concise handoff narrative;
- do not emit a JSON object as a function/tool call.

No web search is required in Protocol A because Web Searcher owns source
discovery in the existing pipeline. `web_search` remains available to preserve
Researcher's existing capability and is optional.

### 5.2 Required and optional interactions

Required:

- Protocol A must reach a valid final response;
- if semantic memory is enabled, `recall_memory` must be attempted before any
  other Researcher tool;
- a `ResearcherHandoff` must be constructed and pass size/secret checks.

Optional:

- `web_search`;
- `send_message`;
- `read_inbox`;
- `blackboard_write`;
- `blackboard_read`;
- `recall_memory` when memory is disabled.

The run must not fail merely because an optional collaboration tool was not
selected by the model. It must fail if a required memory attempt or handoff
construction fails.

### 5.3 Safe retry policy

Protocol A automatic retries are bounded to **one retry** and classified by
collector state:

| Failure state | Action |
|---|---|
| Provider/network failure before any tool action | Retry Protocol A once |
| Failure after only read-only actions (`recall_memory`, `read_inbox`, `blackboard_read`, `web_search`) | Retry once, recording a new attempt |
| Failure after successful `send_message` or `blackboard_write` | Do not retry automatically; fail the run |
| Ambiguous side-effect result (timeout after request sent) | Do not retry; fail conservatively |
| Invalid raw final response with no side effect | Retry once with stricter instruction |
| Cancellation or deadline | Do not retry; terminal cancel/timeout |

A retry creates a fresh Protocol A task/agent but reuses the same run context
only for read-only state. It must not reuse mutable LLM executor state. The
collector records the prior attempt and the new attempt. The handoff includes
only the final successful attempt plus attempt metadata.

If a side-effecting operation completed and the provider later fails, the run
must fail with a stage-specific error. The user can use the existing whole-run
retry endpoint, which creates a new run; it must not replay a partially known
Protocol A attempt inside the same run.

## 6. Protocol B design and retry policy

### 6.1 Crew shape

Kickoff 2 contains:

```text
No-tools Researcher formatter
  -> Web Searcher
  -> Analyst
  -> Report Writer
```

The formatter:

- uses the same configured LLM/provider/model;
- has `tools=[]`;
- has `output_json=SubQuestions`;
- receives the serialized `ResearcherHandoff` as an explicit input;
- does not receive the Protocol A agent or its tools.

For Groq, this produces a no-tools structured-output request. The
`GroqCompatibleLLM` remains selected and continues removing only
`cache_breakpoint`.

### 6.2 Formatter validation

The formatter result must satisfy both:

1. CrewAI's declared `SubQuestions` output model.
2. Coraxis explicit `SubQuestions.model_validate(...)` validation and
   `is_usable` check before Web Searcher starts.

Invalid JSON, invalid schema, or fewer than `MIN_SUB_QUESTIONS` usable
questions is a visible Protocol B failure. There is no prose fallback and no
success-shaped empty model.

### 6.3 Exact downstream context isolation

The second Crew must construct task objects in this order:

```text
formatter_task
search_task(context=[formatter_task])
analyse_task(context=[search_task])
report_task(context=[analyse_task])
```

The formatter task receives the handoff through its own description/input
placeholder. `search_task` must explicitly set `context=[formatter_task]`.
This is required because CrewAI 1.15.37 otherwise aggregates all prior raw
outputs when `context` is omitted.

The Web Searcher therefore receives the formatter's raw validated JSON only,
not Protocol A raw prose or the handoff envelope. It still receives the
original `{query}` input through its own description. The formatter's output
is the same `SubQuestions` contract consumed by the existing search prompt.

The downstream tasks should continue using explicit immediate-predecessor
contexts to avoid accidental accumulation:

- Analyst sees only `RawFindings`;
- Report Writer sees only `AnalyzedFindings`.

This is a public CrewAI arrangement; no private executor state is needed.

### 6.4 Formatter retry

Protocol B retries only the formatter, maximum **two retries**:

1. reuse the exact same immutable handoff object and digest;
2. create a fresh no-tools formatter task/agent;
3. never reconstruct or rerun Protocol A;
4. apply a stricter format instruction after a validation failure;
5. record attempt number, failure category, and token usage.

After the retry cap, fail the run explicitly. Web Searcher must not start until
formatter validation succeeds.

## 7. Events, persistence, cancellation, and SSE

### 7.1 Event names and ordering

Use existing enum values from
[`src/coraxis/db/enums.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/db/enums.py);
do not add a migration for stage names. Add payload fields:

```json
{
  "protocol": "A|B",
  "stage": "native_tools|structured_output",
  "attempt": 1
}
```

Required order:

```text
run.started
agent.started {agent: researcher, protocol: A, stage: native_tools}
tool.started / tool.completed
agent.progress {agent: researcher, protocol: A, stage: handoff_created}
agent.completed {agent: researcher, protocol: A}
agent.started {agent: researcher, protocol: B, stage: structured_output}
agent.completed {agent: researcher, protocol: B}
agent.started {agent: web_searcher}
tool.started / tool.completed
agent.completed {agent: web_searcher}
agent.started {agent: analyst}
...
report.ready
run.succeeded
```

Failures use `agent.failed` followed by the existing terminal run failure
event. Tool events continue to be emitted by `ToolContext.publish()`.

### 7.2 Persistence

`EventRecorder` remains the only event persistence/broadcast path. Events are
persisted before the in-process bus publishes them, preserving SSE replay
ordering.

Add bounded run stats, without schema changes:

```json
{
  "researcher_protocol": "two_protocol",
  "protocol_a_attempts": 1,
  "protocol_b_attempts": 1,
  "protocol_a_tool_actions": 4,
  "protocol_a_side_effects": 1,
  "handoff_bytes": 18432,
  "handoff_truncated": false,
  "handoff_digest": "<digest>",
  "structured_output_retries": 0,
  "token_usage": {
    "protocol_a": "N/A or measured",
    "protocol_b": "N/A or measured"
  }
}
```

Do not persist the complete handoff, raw prompts, tool payloads, secrets, or
private CrewAI messages in run stats or events.

### 7.3 Cancellation and timeout

Before Protocol A, before handoff construction, before Protocol B, and before
Web Searcher starts, check the existing `StopSignal`.

- cancellation between stages: mark the run cancelled; do not start Protocol B;
- timeout during Protocol A: do not retry; mark timed out;
- timeout during Protocol B: do not retry if the deadline is exhausted;
- cancellation during Protocol B: do not start downstream tasks;
- cancellation/timeout after side effects: preserve event history and terminal
  status; never replay the stage automatically.

The existing `finally` path must still close the fetcher, stop the watcher, and
flush the recorder on every kickoff path.

## 8. Provider and custom-agent compatibility

### 8.1 Initial rollout

Enable the two-protocol path only when all of the following hold:

- built-in pipeline;
- Researcher provider is Groq;
- model is the configured Groq model, initially
  `openai/gpt-oss-120b` through the Groq-compatible configuration.

All non-Groq providers retain the current four-task single-Crew behavior in the
first implementation. Their existing output behavior must remain unchanged.

The provider gate must be explicit and observable in run stats. It must not
silently alter a custom provider merely because its endpoint is
OpenAI-compatible.

### 8.2 Custom teams and custom agents

Do not apply the built-in two-protocol transformation to `build_team_crew()` or
arbitrary custom teams in the first rollout. Custom teams have user-defined
tasks, tools, roles, and expected outputs; inserting a Researcher formatter
would change their semantics and external contracts.

For a custom agent whose slug is `researcher`, preserve current behavior unless
the run is the built-in pipeline identified by the resolved built-in four-agent
set. Record the gate decision in debug logs/run stats without exposing
credentials.

## 9. Exact implementation sequence

### Stage 0 — Baseline and contract guard

Expected files:

- `tests/unit/test_tasks.py` or the repository's existing task-test location;
- new focused two-protocol test module if needed.

Work:

- lock current `SubQuestions` serialization and usability expectations;
- add tests that current non-Groq task construction remains unchanged;
- add a test that the Groq gate does not select custom teams.

### Stage 1 — Collector and sanitization

Expected files:

- [`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py);
- [`src/coraxis/agents/tools/crew_tools.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tools/crew_tools.py);
- [`src/coraxis/agents/comms.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/comms.py)
  only if a lock-safe snapshot helper is needed;
- focused collector/sanitization tests.

Work:

- add run-local collector ownership to `ToolContext`;
- add typed records and tool-specific allowlists;
- instrument all six listed tools;
- add redaction, digest, per-field limits, total 64 KiB truncation, and
  immutable snapshot creation;
- preserve normal tool return strings and existing citation behavior.

Deterministic tests:

- each tool creates exactly one success/failure record;
- failures are recorded explicitly;
- `for_agent()` shares the collector but preserves agent attribution;
- two contexts/runs cannot see each other's records;
- side-effect flags are correct;
- redaction removes credential-like values;
- full page text and raw request headers are absent;
- truncation is byte-bounded, deterministic, and UTF-8-safe;
- snapshot mutation after creation cannot change the handoff.

### Stage 2 — Protocol A builder

Expected files:

- [`src/coraxis/agents/tasks.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tasks.py);
- [`src/coraxis/agents/crew.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/crew.py);
- focused task/crew tests.

Work:

- add a raw Researcher Protocol A task without output JSON/Pydantic;
- keep the six existing Researcher tools;
- add a dedicated Protocol A single-task Crew builder;
- define required/optional tool policy in the task instructions.

Deterministic tests:

- Protocol A declares all expected tools;
- Protocol A has no structured output model;
- Protocol A has no JSON response-format configuration;
- task instructions require memory-first only when enabled by runtime policy;
- optional tools are not treated as mandatory.

### Stage 3 — Protocol B and explicit downstream context

Expected files:

- [`src/coraxis/agents/tasks.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tasks.py);
- [`src/coraxis/agents/crew.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/crew.py);
- focused context-isolation tests.

Work:

- add a no-tools formatter agent/task with `output_json=SubQuestions`;
- add the second kickoff builder;
- set `search_task.context=[formatter_task]`;
- set downstream contexts to immediate predecessor tasks;
- explicitly validate formatter output before downstream execution.

Deterministic tests:

- formatter has zero tools;
- formatter has `SubQuestions`;
- Web Searcher context contains formatter output only;
- Web Searcher context excludes Protocol A raw output and the handoff envelope;
- Analyst receives only `RawFindings`;
- Report Writer receives only `AnalyzedFindings`;
- invalid formatter output prevents Web Searcher execution.

### Stage 4 — Orchestrator integration

Expected files:

- [`src/coraxis/services/research.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/services/research.py);
- possibly [`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py)
  for stage metadata;
- research/event/persistence tests.

Work:

- add the explicit Groq built-in-pipeline gate;
- execute kickoff 1, collect and freeze the handoff;
- execute kickoff 2 with the handoff input;
- implement stage-specific retry policy;
- add stage events and stats;
- preserve existing final report/source/claim/memory persistence.

Deterministic tests:

- stage order and event sequence are monotonic;
- Protocol B retry never calls a Protocol A tool;
- Protocol A side-effect failure is not automatically replayed;
- cancellation and timeout between kickoffs are terminal;
- final persistence is unchanged;
- stats distinguish measured values from `N/A`.

### Stage 5 — Adapter regression

Expected files:

- [`tests/unit/test_groq_compatibility.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/tests/unit/test_groq_compatibility.py)
  or its actual repository location.

Work:

- verify both Protocol A and Protocol B use the existing Groq adapter;
- verify Protocol A retains native tools after cache-marker sanitization;
- verify Protocol B remains tools-free;
- make no adapter implementation change unless a focused regression proves
  one is required.

### Stage 6 — Isolated live diagnostics

Use the existing isolated temporary environment and configured credential
without printing or persisting it. Do not modify the main environment.

Run, in order:

1. Protocol A with the configured Groq model and a harmless local tool;
2. Protocol B with a captured handoff and no tools;
3. Protocol B invalid-output retry using a controlled validation failure;
4. one full four-agent pipeline case with real search/fetch/citation/persistence;
5. async execution and SSE/event-order verification;
6. concurrent-run isolation check.

Record only redacted schemas, statuses, metrics, and errors in a new diagnostic
directory. Do not rerun the ten-case benchmark in this phase.

## 10. Verification and rollback

### 10.1 Required verification commands

The exact repository test commands should be used, with the smallest selectors
first:

1. collector/context tests;
2. task/crew construction tests;
3. research/event/persistence tests;
4. Groq adapter tests;
5. full backend suite, Ruff, formatting, and MyPy;
6. isolated live diagnostics.

No dependency installation is permitted unless a changed manifest or a missing
tool explicitly requires it. This plan changes no manifests.

### 10.2 Rollback criteria

Disable the two-protocol gate and return to the prior path if any of these
occur:

- Protocol A tools are repeated after an acknowledged side effect;
- handoff data crosses run boundaries;
- formatter request contains native tools;
- Web Searcher sees Protocol A raw output unexpectedly;
- event sequence/replay loses or reorders events;
- cancellation leaves a nonterminal run;
- non-Groq behavior changes;
- final `SubQuestions` or downstream API contracts change;
- secrets appear in records, events, logs, or reports;
- controlled live Groq run still produces an undeclared JSON tool call.

Rollback must not use reset, clean, stash, discard, or database migration
reversal. It is a provider-gate/code-path selection change.

## 11. Conditions before the ten-case benchmark

Do not rerun Phase 02F until every item passes:

- [ ] Collector tests cover all six tools and failure paths.
- [ ] Handoff is immutable, run-scoped, redacted, and <= 65,536 UTF-8 bytes.
- [ ] Protocol A sends native tools but no structured output configuration.
- [ ] Protocol B sends no native tools and returns validated `SubQuestions`.
- [ ] Explicit `context=[formatter_task]` isolation test passes.
- [ ] Protocol B retries reuse the same snapshot and never rerun tools.
- [ ] Protocol A side-effect retry policy passes deterministic tests.
- [ ] Event persistence and SSE replay remain ordered and gap-free.
- [ ] Cancellation and timeout tests pass between stages.
- [ ] Token/retry statistics distinguish measured values from unavailable values.
- [ ] Non-Groq single-stage behavior passes regression tests.
- [ ] Custom-team/custom-agent behavior is unchanged.
- [ ] Existing cache-breakpoint adapter tests pass.
- [ ] One controlled live four-agent Groq run succeeds.
- [ ] Search, fetch, citation, report, memory, and persistence paths succeed.
- [ ] No undeclared `json`/`JSON` tool call occurs.
- [ ] Phase 02A baseline and prior evaluation outputs remain unchanged.
- [ ] No secrets appear in diagnostic outputs.

## 12. Remaining risks

1. Two kickoffs add latency and token cost.
2. Provider usage accounting may not expose per-stage tokens consistently;
   unavailable values must remain `N/A`.
3. A model may omit useful planning facts from its Protocol A prose even when
   tool records exist; the formatter must treat missing facts as unknown.
4. Search snippets, memory claims, and collaboration text can contain
   user-sensitive content; redaction and bounded allowlists must be tested
   before live use.
5. A timeout after a side-effect request is inherently ambiguous; conservative
   failure is safer than duplicate messaging or blackboard writes.
6. CrewAI public task context aggregates raw output, so any future task
   reordering or omitted explicit context can reintroduce leakage.
7. The existing Groq adapter uses a private CrewAI preparation hook and must be
   retested on every CrewAI upgrade.
8. Custom provider endpoints may have Groq-like restrictions but are
   intentionally outside the initial gate.

## 13. Exact files expected to change during implementation

Expected production changes:

- [`src/coraxis/agents/context.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/context.py)
  — collector ownership, records, snapshot construction, and redaction
  boundary.
- [`src/coraxis/agents/tools/crew_tools.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tools/crew_tools.py)
  — explicit capture around the six tool implementations.
- [`src/coraxis/agents/tasks.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/tasks.py)
  — Protocol A raw task, Protocol B formatter task, and explicit downstream
  context.
- [`src/coraxis/agents/crew.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/crew.py)
  — two kickoff builders and Groq built-in-pipeline selection boundary.
- [`src/coraxis/services/research.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/services/research.py)
  — stage orchestration, retries, cancellation checks, events, and stats.

Possible supporting change:

- [`src/coraxis/agents/comms.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/agents/comms.py)
  — only if the existing lock-protected channel snapshots need a typed frozen
  snapshot helper.

Expected test changes/additions:

- `tests/unit/test_groq_compatibility.py`;
- task/crew construction tests at the repository's existing test location;
- collector/context tests;
- research/event/persistence tests;
- live diagnostic runner/output files outside source and baseline directories.

Explicitly not expected to change:

- [`src/coraxis/services/llm/groq_compat.py`](C:/Users/shulk/OneDrive/Desktop/Researcher/src/coraxis/services/llm/groq_compat.py),
  except for a proven adapter regression;
- dependency manifests or lockfiles;
- database migrations;
- `SubQuestions` external fields;
- custom-team task semantics;
- Phase 02A–02F existing reports or baseline data.

## 14. Final decision summary

### Decisions made

- Use Option A.
- Use two Coraxis-controlled kickoffs.
- Add a run-local explicit collector to `ToolContext`.
- Build a 64 KiB immutable, sanitized handoff.
- Use a no-tools formatter with `SubQuestions`.
- Use `context=[formatter_task]` for Web Searcher and immediate predecessor
  contexts downstream.
- Roll out Groq built-in pipeline first.
- Keep non-Groq and custom-team behavior unchanged.
- Retry Protocol A only when no side effects are present; retry Protocol B
  only with the same snapshot, at most twice.
- Use existing event types and persistence paths.

### Remaining risks

- Added latency/cost and incomplete provider token accounting.
- Potentially incomplete Protocol A narrative.
- Sensitive content in tool results requires strict redaction tests.
- Ambiguous side-effect timeouts require conservative failure.
- CrewAI and adapter upgrades require regression testing.

### Exact files expected to change

`context.py`, `crew_tools.py`, `tasks.py`, `crew.py`, and `services/research.py`,
plus focused tests; `comms.py` only if a typed snapshot helper is required.
No dependencies, migrations, baseline data, existing reports, or external
contracts should change.

STOP CONDITION: this V2 document is the deliverable. No implementation or
benchmark execution is authorized by this plan.

