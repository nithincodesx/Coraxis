# Coraxis Researcher Two-Protocol Implementation Plan

## 1. Executive summary

The current Researcher task combines two incompatible protocols:

1. Native function/tool calling for Coraxis tools.
2. Structured `SubQuestions` output through `Task(output_json=SubQuestions)`.

CrewAI 1.15.37 routes the tool-enabled execution through its native-tool path.
The Groq GPT-OSS model then attempts an undeclared `json`/`JSON` tool call,
which Groq rejects. Direct JSON mode works without tools, and direct function
calling works with declared tools, but Groq rejects JSON mode together with
function tools.

The recommended implementation is **Option A: two-stage Researcher
orchestration**:

1. **Protocol A — Research/tool stage:** a normal CrewAI agent with the
   existing Researcher tools and no structured `output_json`/JSON mode.
2. **Protocol B — Structured-output stage:** a separate no-tools CrewAI agent
   task that receives the complete Protocol A result and produces validated
   `SubQuestions`.

This preserves the existing downstream `SubQuestions` contract while keeping
native tools and structured JSON in separate requests. It uses public CrewAI
construction APIs (`Agent`, `Task`, `Crew`, `context`, `output_json`) rather
than overriding CrewAI internals. The existing Groq adapter remains responsible
only for removing `cache_breakpoint`.

This document is planning-only. No application code, dependency file,
database migration, benchmark case, baseline, existing report, commit, or
push was changed.

## 2. Existing execution architecture

### 2.1 Current four-agent pipeline

The built-in sequential pipeline is constructed in
[`src/coraxis/agents/crew.py`](src/coraxis/agents/crew.py):

```text
Researcher -> Web Searcher -> Analyst -> Report Writer
```

`build_pipeline_crew()` creates four CrewAI `Agent` objects and four sequential
`Task` objects from `build_pipeline_tasks()`.

The Researcher task currently:

- receives Researcher tools;
- asks the model to call `recall_memory` first;
- requests JSON matching `SubQuestions`;
- sets `output_json=SubQuestions`.

The Researcher tools are:

- `web_search`
- `recall_memory`
- `send_message`
- `read_inbox`
- `blackboard_write`
- `blackboard_read`

The registry and tool factories are in
[`src/coraxis/agents/tool_registry.py`](src/coraxis/agents/tool_registry.py).
Tool implementations use the per-run `ToolContext` in
[`src/coraxis/agents/context.py`](src/coraxis/agents/context.py).

### 2.2 Current structured-output boundary

[`src/coraxis/agents/tasks.py`](src/coraxis/agents/tasks.py) defines
`SubQuestions`, `PlannedSubQuestion`, and the Researcher task. The current task
declares:

```python
output_json=SubQuestions
```

CrewAI 1.15.37 copies that model into its executor response model. When native
tools are present, the executor calls the LLM with the tool schemas and no
`response_format`. The model can therefore attempt a synthetic JSON tool call.

The remaining tasks also use `output_json`:

- `RawFindings`
- `AnalyzedFindings`
- `FinalReport`

They must not be changed as part of this Researcher-specific design unless
later live evidence shows the same incompatibility for those agents.

### 2.3 Current LLM boundary

[`src/coraxis/services/llm/factory.py`](src/coraxis/services/llm/factory.py)
selects `GroqCompatibleLLM` only for Groq. Other providers use the normal
CrewAI `LLM`.

[`src/coraxis/services/llm/groq_compat.py`](src/coraxis/services/llm/groq_compat.py)
deep-copies prepared messages and removes only `cache_breakpoint`. It does not
change tools, `tool_choice`, `response_format`, or output schemas. The
two-protocol design must preserve this narrow responsibility.

### 2.4 Current run lifecycle

[`src/coraxis/services/research.py`](src/coraxis/services/research.py) owns:

1. resolving agent specifications and credentials;
2. creating one per-run `ToolContext`;
3. creating the `EventRecorder`;
4. starting cancellation monitoring;
5. calling `crew.kickoff_async(inputs={"query": ...})`;
6. parsing the final `FinalReport`;
7. persisting sources, claims, report, statistics, and memory;
8. writing terminal run status.

The `EventRecorder` persists events before broadcasting them through
[`src/coraxis/services/events.py`](src/coraxis/services/events.py). SSE clients
replay persisted events by sequence number before receiving live events.

Run persistence remains at the final `FinalReport` boundary in
[`src/coraxis/repositories/runs.py`](src/coraxis/repositories/runs.py).
The Researcher protocol split should not require a database migration.

## 3. Architecture questions and answers

### 3.1 Can CrewAI 1.15.37 support the split with public APIs?

**Yes, with an explicit two-task composition; no, as an in-place mutation of
one task's executor.**

Public APIs available in the tested release include:

- `Agent(..., tools=[...], llm=...)`
- `Task(..., agent=..., context=[...])`
- `Task(output_json=SubQuestions)`
- `Crew(..., tasks=[...], process=Process.sequential)`
- `Crew.kickoff_async(...)`

There is no verified public API that changes a task from native tools to
structured output midway through one executor invocation. Therefore the
implementation should not override `AgentExecutor`, `call_llm_native_tools`,
or other private CrewAI internals.

### 3.2 Does the current Researcher task execute both protocols indivisibly?

For the current task, yes. `output_json=SubQuestions` is attached to the same
tool-enabled task. CrewAI decides the native-tool path and structured-output
handling inside its private executor lifecycle. Coraxis cannot safely insert a
second public request inside that executor.

### 3.3 Where should the split be inserted?

Insert it at Coraxis's task/crew construction boundary:

- Protocol A becomes a tool-enabled raw-output task.
- Protocol B becomes a no-tools structured-output task.
- The normal Web Searcher task receives Protocol B's `SubQuestions` output.

The preferred implementation is a single sequential Crew containing:

```text
Research/tool task
  -> Structured-output task
  -> Web Searcher
  -> Analyst
  -> Report Writer
```

The alternative is two Crew kickoffs coordinated by Coraxis. The single Crew
is preferred initially because CrewAI already provides public `context` passing
and preserves one run-level lifecycle. The two-kickoff alternative is a
fallback if context size or task-result behavior cannot safely preserve the
Protocol A material.

### 3.4 Can Protocol A return enough information?

Yes, if its raw expected output explicitly requires a compact, complete
Researcher work record containing:

- original query;
- question classification clues;
- all proposed sub-question material;
- key entities;
- search strategy;
- relevant memory findings;
- tool results needed to explain the plan;
- collaboration messages that affect the plan.

The stage must not rely on hidden `agent.last_messages` as the contract.
CrewAI's public `TaskOutput.raw` is the stable handoff candidate. If the full
native conversation is required, Coraxis should explicitly capture a
redacted/size-bounded Protocol A transcript through existing event/context
plumbing rather than reaching into private executor state.

### 3.5 How does Protocol B receive actual tool results?

Protocol B receives the Protocol A `TaskOutput` through public CrewAI task
context. The context should contain a serialized, size-bounded
`ResearcherToolResult` envelope, not arbitrary internal CrewAI objects.

The envelope should include:

- the original query;
- Protocol A's final raw output;
- structured tool-result summaries emitted by Coraxis tools;
- memory recall results needed for planning;
- collaboration messages/blackboard values relevant to the final plan;
- a list of completed tool actions for observability and retry decisions.

Sensitive request content must not be copied into logs or SSE payloads merely
to support this handoff. The structured context passed to the LLM may contain
the research content needed for the plan, subject to existing context limits.

### 3.6 How are memory and collaboration messages preserved?

Protocol A continues using the same per-run `ToolContext`, `AgentChannel`,
recall callback, and blackboard/message tools. Protocol B receives a snapshot
of only the relevant outputs. It should not receive native tools and should
not perform new memory or collaboration actions.

The snapshot must be created after Protocol A completes and before Protocol B
starts. It must be run-local, immutable after creation, and never stored in
process-global state.

### 3.7 How do events and SSE behave?

Existing tool events remain unchanged:

```text
agent/tool events from Protocol A
-> researcher structured-stage started
-> researcher structured-stage completed
-> web_searcher started
-> ...
-> report.ready
-> run.succeeded
```

The current `EventType` enum already supports agent progress and tool events.
If stage-specific visibility is required, use existing `AGENT_PROGRESS` events
with a `stage` payload first. Adding new event enum values is optional and
should be deferred until frontend requirements are confirmed.

Every event must continue through `EventRecorder`, so it is persisted before
being broadcast and receives a monotonic sequence. Do not publish stage events
directly through the event bus.

### 3.8 How do retries work?

Protocol A and Protocol B need separate bounded retry scopes:

- A transient Protocol A provider failure may retry the whole Protocol A task,
  because tool actions may have partially occurred.
- A Protocol B validation/provider failure may retry Protocol B only, reusing the
  immutable Protocol A snapshot. It must not repeat completed tool actions.
- If Protocol B repeatedly fails validation, the run must fail explicitly rather
  than falling back to an unvalidated `SubQuestions` object.

Retry metadata should be emitted as agent progress and included in operational
stats, without exposing prompts, keys, or full sensitive payloads.

### 3.9 How do token accounting and persistence work?

Both stages use the same configured LLM boundary and existing CrewAI/LiteLLM
usage tracking. The implementation should aggregate stage usage into the
existing run stats rather than create a new persistence schema.

The final `SubQuestions` object remains in-memory handoff data. Existing source,
claim, report, and memory persistence continues at the end of the run. If
stage diagnostics are persisted, store only bounded, non-secret metadata in the
existing run stats JSON; do not add a migration for the first implementation.

### 3.10 Can the downstream pipeline remain unchanged?

Yes. Protocol B must return the same `SubQuestions` model. The Web Searcher
continues receiving the same task context shape, and Analyst/Report Writer
remain unchanged. This is the primary compatibility invariant.

## 4. Proposed execution architecture

### 4.1 Protocol A — native research and tool execution

Construct a Researcher agent with the current six tools and the Groq-compatible
LLM. Construct a task with:

- no `output_json`;
- no `output_pydantic`;
- no `response_format`;
- an explicit raw-output envelope requirement;
- explicit instructions to use tools before finalizing;
- a bounded final response containing all planning facts needed by Protocol B.

The task may still call `recall_memory`, web search, and collaboration tools.
The model's native tool calls remain declared Coraxis tools. The task should not
ask the model to emit a JSON object as a tool call.

The raw output can be plain text or a deliberately simple text envelope. The
first implementation should avoid a second Pydantic schema in the
tool-enabled stage because the incompatibility is precisely the combination
of native tools and structured output.

### 4.2 Protocol B — no-tools structured output

Construct a separate Researcher formatter/planner agent with:

- the same provider/model configuration;
- no native tools;
- the same Groq adapter when provider is Groq;
- a task whose context is the Protocol A snapshot;
- `output_json=SubQuestions`.

Because no tools are attached, CrewAI can use its structured-output path
without sending function tools to Groq. The result must be validated explicitly
with `SubQuestions.model_validate(...)` or equivalent CrewAI output validation.

Protocol B must be instructed to preserve evidence from Protocol A, not invent
tool results, and mark missing information conservatively.

### 4.3 Downstream handoff

The Web Searcher task should consume only the validated Protocol B
`SubQuestions` output. The downstream task prompt and output model remain
unchanged unless a focused test proves a context-shape mismatch.

### 4.4 Public/private boundary

| Concern | Planned API | Status |
|---|---|---|
| Construct tool agent | CrewAI public `Agent` constructor | Supported |
| Construct raw tool task | CrewAI public `Task` without output model | Supported |
| Pass stage result | CrewAI public `Task.context` / sequential task context | Supported |
| Construct no-tools formatter | CrewAI public `Agent(tools=[])` | Supported |
| Structured result | CrewAI public `Task(output_json=SubQuestions)` | Supported when no tools |
| Run asynchronously | CrewAI public `Crew.kickoff_async()` | Supported |
| Remove cache marker | Existing Coraxis adapter uses private CrewAI preparation method | Existing accepted risk |
| Inspect executor internals | Not planned | Prohibited for implementation |

The only private API remains the already-approved cache-marker adapter. The
two-protocol design must not add another private CrewAI override.

## 5. Option A versus Option B

### Option A — two-stage orchestration

**Flow:** native tool task -> no-tools structured-output task.

| Criterion | Assessment |
|---|---|
| GPT-OSS 120B reliability | Strongest verified direction; no tools are present in the JSON stage |
| CrewAI complexity | Moderate; requires a formatter agent/task and context envelope |
| API dependency | Public CrewAI task/agent/context APIs |
| Tool-result preservation | Explicit snapshot; testable and auditable |
| Sync behavior | Supported through existing Crew kickoff paths |
| Async behavior | Supported through `kickoff_async`; must be tested separately |
| Error handling | Stage-specific failures and retries |
| Retry semantics | Protocol B can retry without repeating Protocol A tools |
| Token/cost | Two LLM requests; additional prompt and output tokens |
| SSE/activity | Preserves tool events; adds stage progress events |
| Other providers | Can be Groq-gated first; normal providers may retain one-stage path |
| Maintenance | Clear protocol boundary; fewer provider-specific assumptions |

### Option B — declared `emit_subquestions` tool

**Flow:** native Researcher tools plus one declared structured-output function
tool whose arguments match `SubQuestions`.

| Criterion | Assessment |
|---|---|
| GPT-OSS 120B reliability | Unverified for the complete CrewAI prompt and retry lifecycle |
| CrewAI complexity | Lower initial code size, but tighter native-tool/parser coupling |
| API dependency | Public tool registration, but output conversion is Coraxis-owned |
| Tool-result preservation | Native, but model must select the correct declared tool |
| Sync behavior | Likely possible; requires live validation |
| Async behavior | Requires separate validation |
| Error handling | Tool-call argument validation and undeclared/synthetic call failures remain possible |
| Retry semantics | Native retries may repeat tools or emit malformed structured calls |
| Token/cost | Usually one request path, but retries may be expensive |
| SSE/activity | Natural tool event, but introduces a new product-visible pseudo-action |
| Other providers | Could work, but changes the shared Researcher contract |
| Maintenance | Depends on model-specific tool-selection behavior and schema stability |

Option B is not recommended merely because a direct `echo` function call
worked. The current failure is specifically inside CrewAI's combined native
tool plus structured-output lifecycle, and a declared formatter tool would
still need full live validation with the actual Researcher prompt, schemas,
retries, SSE, and both sync/async execution.

## 6. Recommended implementation

Implement Option A first, gated by provider capability:

1. Add a Coraxis-owned Researcher protocol builder that creates the raw
   tool-enabled stage and no-tools formatter stage.
2. Keep the existing Researcher tool registry and `ToolContext`.
3. Add a bounded immutable handoff envelope.
4. Use a separate formatter Agent/Task with `tools=[]` and
   `output_json=SubQuestions`.
5. Validate `SubQuestions` before allowing Web Searcher execution.
6. Keep non-Groq providers on the existing single-task path initially, unless
   a shared implementation can be proven behaviorally identical.
7. Emit stage progress through the existing `EventRecorder`.
8. Aggregate stage usage and retry counts into existing run stats.
9. Fail explicitly when structured conversion cannot be validated.

The implementation should not silently drop Researcher tools, downgrade to
unstructured output, or parse arbitrary prose into a success-shaped
`SubQuestions`.

## 7. Event, persistence, and retry design

### 7.1 Event ordering

Proposed logical events:

```text
run.started
agent.started(researcher, stage=tool_execution)
tool.started / tool.completed
agent.progress(researcher, stage=structured_output, retry=...)
agent.completed(researcher)
agent.started(web_searcher)
...
run.succeeded
```

The exact agent lifecycle events emitted by CrewAI should be verified before
implementation. Coraxis-created stage events must use `EventRecorder.emit()`.
They must never be broadcast directly.

### 7.2 Persistence

No schema change is required initially:

- existing sources and claims remain in `CitationTracker`;
- final report persistence remains unchanged;
- existing run stats can add bounded keys such as
  `researcher_protocols`, `structured_output_retries`, and per-stage usage;
- no raw prompt, API key, authorization header, or unrestricted tool transcript
  should be persisted.

Historical run records remain readable because the final report and downstream
models do not change.

### 7.3 Cancellation and timeout

Both stages share the existing `StopSignal` through the same `ToolContext`.
Before starting Protocol B, check cancellation. A timeout in either stage
must use the existing terminal status path and must not leave the run in
`running`.

### 7.4 Retry policy

Suggested bounded policy:

- Protocol A: use existing CrewAI retry behavior for provider/tool failures;
  do not automatically replay completed side-effecting tools without an
  idempotency decision.
- Protocol B: retry only the no-tools formatter using the same immutable
  snapshot.
- Schema validation failure: retry with a stricter format instruction and a
  bounded count; after the cap, mark the run failed.
- No fallback to unvalidated text.

## 8. Exact expected future file changes

Implementation approval would likely affect:

1. [`src/coraxis/agents/tasks.py`](src/coraxis/agents/tasks.py)
   - split the current Researcher task into raw Protocol A and structured
     Protocol B task builders;
   - keep `SubQuestions` unchanged unless tests prove a schema issue.
2. [`src/coraxis/agents/crew.py`](src/coraxis/agents/crew.py)
   - add explicit no-tools formatter-agent construction or a protocol-specific
     pipeline builder;
   - preserve normal custom-team behavior.
3. [`src/coraxis/services/research.py`](src/coraxis/services/research.py)
   - integrate stage events, cancellation checks, stage retries, and handoff
     validation if the split cannot be represented entirely by one Crew.
4. [`src/coraxis/agents/context.py`](src/coraxis/agents/context.py)
   - only if a bounded handoff snapshot or stage-local result collector is
     needed; preserve per-run isolation.
5. [`src/coraxis/services/llm/groq_compat.py`](src/coraxis/services/llm/groq_compat.py)
   - likely no change; retain only cache-marker sanitization.
6. [`tests/unit/test_tasks.py`](src/coraxis/tests/unit/test_tasks.py) or the
   repository's existing task-test location
   - deterministic task construction and output-boundary tests.
7. [`tests/unit/test_groq_compatibility.py`](src/coraxis/tests/unit/test_groq_compatibility.py)
   - verify the adapter still preserves stage messages and tools.
8. New focused two-protocol orchestration tests.
9. Existing research, event, persistence, and API tests as needed.

No dependency manifest, lockfile, migration, baseline, or benchmark definition
should change for this feature.

## 9. Detailed deterministic test plan

### 9.1 Construction and protocol separation

1. Protocol A has the six expected Researcher tools.
2. Protocol A has no `output_json`, `output_pydantic`, or JSON response format.
3. Protocol B has zero native tools.
4. Protocol B uses `SubQuestions`.
5. Protocol B cannot accidentally inherit the Researcher tool list.
6. The Web Searcher receives the same validated `SubQuestions` shape as before.

### 9.2 Handoff and validation

1. Tool results are present in the immutable Protocol A snapshot.
2. Memory recall results are preserved.
3. Collaboration messages and blackboard values needed by the plan are
   preserved.
4. Protocol B receives only the bounded snapshot and original query.
5. Valid structured JSON produces a `SubQuestions` instance.
6. Invalid JSON raises a visible validation failure.
7. Missing required planning content does not become a success-shaped fallback.
8. Oversized tool results are bounded deterministically without changing the
   downstream contract.

### 9.3 Retry and side effects

1. Protocol B retry reuses the same snapshot.
2. Protocol B retry does not invoke Protocol A tools.
3. Protocol A failure is surfaced with the original error and stage.
4. Cancellation between stages produces a terminal cancelled run.
5. Timeout during either stage produces a terminal timed-out run.
6. Retries are bounded and recorded.

### 9.4 Events and persistence

1. Tool events precede structured-stage completion.
2. Event sequence numbers remain monotonic.
3. Events are persisted before SSE broadcast.
4. SSE replay after reconnect contains both stages in order.
5. Terminal events are emitted exactly once.
6. Final run persistence contains the same report/source/claim contract.
7. Stage metadata does not expose credentials or unrestricted sensitive
   content.

### 9.5 Provider and concurrency regression

1. Non-Groq providers retain existing behavior.
2. Groq adapter removes only `cache_breakpoint`.
3. Sync execution works where supported by existing tool bridges.
4. Async execution through `kickoff_async()` works.
5. Two concurrent runs do not share handoff snapshots, channels, trackers, or
   retry state.
6. MCP imports and existing Coraxis tool interfaces remain unchanged.

## 10. Live diagnostic plan

Before any benchmark rerun, run a small isolated diagnostic using the exact
versions and configured model:

1. Current GPT-OSS 120B, Protocol A with `recall_memory` and one harmless local
   tool; verify native tool completion.
2. Protocol B with the captured Protocol A snapshot and no tools; verify valid
   `SubQuestions`.
3. One full four-agent pipeline case using the actual search/fetch/citation
   path.
4. Repeat the structured stage once after an induced validation failure; verify
   no duplicate Protocol A tool call.
5. Test async execution and event ordering.
6. Verify run persistence and SSE replay.
7. Verify no `json`/`JSON` tool call appears in any declared-tool request.
8. Verify the original Phase 02A baseline hashes are unchanged.

All live diagnostics must use a new output directory, redact secrets, and
remain separate from the ten-case benchmark.

## 11. Risks and rollback strategy

### Risks

- Two LLM calls increase latency and cost.
- Protocol A raw output may omit information unless its handoff contract is
  explicit.
- Large tool results can exceed Protocol B context limits.
- Stage-specific events may require frontend handling.
- CrewAI task context behavior may differ between sync and async paths.
- The existing adapter already relies on a private CrewAI method; upgrades
  must retest it.
- Running the formatter with no tools prevents it from independently checking
  facts; it must only transform the Protocol A record.

### Rollback

The implementation should be isolated behind a provider/protocol selection
boundary. Rollback consists of:

1. disabling the Groq two-protocol path;
2. restoring the prior task builder selection;
3. leaving the existing cache-marker adapter unchanged;
4. retaining any new deterministic tests that document the known failure;
5. not altering historical run records or the Phase 02A baseline.

No database migration should be required, making rollback a code/configuration
selection change rather than a data migration.

## 12. Benchmark readiness checklist

The ten-case Phase 02F benchmark must not run until all are true:

- [ ] Researcher native tools execute successfully with GPT-OSS 120B.
- [ ] Protocol B produces valid `SubQuestions`.
- [ ] Protocol B request contains no native tools.
- [ ] JSON mode is never combined with native function tools.
- [ ] No undeclared `json`/`JSON` tool call occurs.
- [ ] A controlled live four-agent pipeline case completes.
- [ ] Search, fetch, citation, and persistence paths are operational.
- [ ] SSE events are ordered and replayable.
- [ ] Sync and async diagnostic paths pass.
- [ ] Deterministic regression suite passes.
- [ ] Non-Groq provider behavior is preserved.
- [ ] MCP and tool interfaces remain intact.
- [ ] Phase 02A baseline hashes remain unchanged.
- [ ] New outputs use a separate directory.

## 13. Unresolved questions

1. Should the first implementation use one sequential Crew with a no-tools
   formatter task, or two Coraxis-controlled Crew kickoffs if CrewAI context
   size is insufficient?
2. What exact bounded envelope size preserves all useful tool results without
   overflowing the formatter context?
3. Should Protocol A's raw output be persisted only as transient handoff data,
   or should bounded stage metadata be added to run stats?
4. Which existing CrewAI lifecycle events are emitted for a second task and
   whether the frontend already renders them correctly?
5. Should the two-protocol path be Groq-only initially, or shared for every
   provider after proving no behavior change?
6. What explicit criteria define “required tool interactions” so the stage can
   fail or continue deterministically?
7. Is a declared `emit_subquestions` tool worth a separate experiment after
   Option A is validated?
8. Does the product require preserving every collaboration message in the
   formatter context, or only messages that affect the final plan?

These questions must be resolved during implementation design review, not by
silently changing the external contract.

## 14. Final planning status

This is a planning-only deliverable.

- Application code: unchanged.
- Dependency files and lockfiles: unchanged.
- Database migrations: unchanged.
- Phase 02A baseline: unchanged.
- Phase 02A–02F reports: unchanged.
- Groq cache-breakpoint adapter: unchanged.
- Ten-case benchmark: not run.
- Commit or push: none.
- Reset, clean, stash, or discard: none.

