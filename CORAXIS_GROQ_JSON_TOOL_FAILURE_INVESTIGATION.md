# Coraxis Groq JSON Tool Failure Investigation

## 1. Executive summary

The Phase 02F live benchmark failure was reproduced with real Groq requests in
an isolated environment using:

- Python 3.11.9
- CrewAI 1.15.37
- LiteLLM 1.105.7
- MCP 1.30.0
- Model: `groq/openai/gpt-oss-120b`

The failure is caused by an interaction between CrewAI structured task output
and native tool calling:

1. The Researcher task declares `output_json=SubQuestions`.
2. The Researcher agent also has native tools.
3. CrewAI enters its native-tool execution path and calls LiteLLM with the
   declared Coraxis tools.
4. CrewAI does not pass `response_format` on that native-tool call.
5. The GPT-OSS model emits a synthetic tool call named `json` or `JSON` for
   the requested structured output.
6. That tool is not in the declared tool list, so Groq rejects the request.

The existing Groq adapter is not the cause. It removes only
`cache_breakpoint`; it preserves the six declared Researcher tools and does not
add or remove JSON tools.

Direct Groq JSON mode works without tools. Direct Groq function calling works
with a correctly declared tool. Groq explicitly rejects combining JSON mode
with function tools. Therefore, adding `response_format=json_object` to the
existing Researcher request is not a safe fix.

No application code, dependency file, lockfile, benchmark case, baseline, or
existing report was modified during this investigation.

## 2. Failed benchmark evidence

The inspected run was:

`evaluation/phase02f_live/run_20261111T2145_utf8/`

Its environment metadata records the exact compatible versions and model.
All ten entries in `status.json` are failures. The failures occur during the
first Researcher/decomposition request, before web search, fetching, evidence
tracking, synthesis, or report writing.

Observed provider errors included:

```text
attempted to call tool 'json' which was not in request.tools
attempted to call tool 'JSON' which was not in request.tools
Failed to parse tool call arguments as JSON
```

The failures share the same execution path:

```text
CrewAI AgentExecutor.call_llm_native_tools
  -> get_llm_response(...)
  -> GroqCompatibleLLM.call(...)
  -> CrewAI LLM._handle_non_streaming_response(...)
  -> litellm.completion(...)
  -> Groq
```

The recorded benchmark run had 0 successful cases and 10 failed cases. No
benchmark was rerun during this investigation.

## 3. Source and request trace

### 3.1 Researcher task

[`src/coraxis/agents/tasks.py`](src/coraxis/agents/tasks.py) constructs the
Researcher task with:

```python
Task(
    ...,
    agent=agents["researcher"],
    output_json=SubQuestions,
)
```

The task prompt asks for JSON matching the `SubQuestions` schema.
`SubQuestions` and `PlannedSubQuestion` are Pydantic models in the same file.

### 3.2 Researcher tools

The Researcher receives these declared tools:

1. `web_search`
2. `recall_memory`
3. `send_message`
4. `read_inbox`
5. `blackboard_write`
6. `blackboard_read`

The first two are Researcher-specific tools. The final four are always
available collaboration tools. These names were inspected from the constructed
CrewAI tool schemas; no secret values were included.

### 3.3 CrewAI structured-output behavior

In CrewAI 1.15.37:

- `Agent._update_executor_parameters()` assigns
  `task.output_json` to `AgentExecutor.response_model`.
- When native tools are present, the executor's native path calls
  `get_llm_response(..., response_model=None)`.
- `get_llm_response()` calls the LLM with `tools=...`.
- The LLM request therefore contains native tools but no JSON
  `response_format`.

The separate CrewAI `response_model`/Instructor path is used when the native
tool path is not active. That path is not the path observed in the failed
Researcher request.

### 3.4 Groq adapter behavior

[`src/coraxis/services/llm/groq_compat.py`](src/coraxis/services/llm/groq_compat.py)
overrides CrewAI's private preparation method and:

- deep-copies prepared messages;
- removes only `cache_breakpoint`;
- preserves roles, content, tools, and metadata;
- does not set `response_format`;
- does not change `tool_choice`;
- does not create a `json` or `JSON` tool.

The redacted prepared request schema was:

```json
{
  "model": "groq/openai/gpt-oss-120b",
  "messages": [
    {"role": "system", "content": "<redacted>"},
    {"role": "user", "content": "<redacted>"}
  ],
  "tools": [
    {"type": "function", "function": {"name": "web_search"}},
    {"type": "function", "function": {"name": "recall_memory"}},
    {"type": "function", "function": {"name": "send_message"}},
    {"type": "function", "function": {"name": "read_inbox"}},
    {"type": "function", "function": {"name": "blackboard_write"}},
    {"type": "function", "function": {"name": "blackboard_read"}}
  ],
  "response_format": null,
  "tool_choice": null
}
```

The original messages contained no `cache_breakpoint` after adapter
preparation.

## 4. Isolated live experiments

All experiments used the real configured Groq credential without printing or
persisting it. Results below distinguish provider calls from local
construction/runtime errors.

| Experiment | Configuration | Result |
|---|---|---|
| A | Direct LiteLLM, `response_format={"type":"json_object"}`, no tools | **PASS**; Groq returned valid JSON |
| B | Direct LiteLLM, one declared `echo` function tool | **PASS**; Groq returned a declared `echo` tool call |
| C | CrewAI `LLM.call(..., response_model=Minimal)` with standard LLM | **PASS**; structured response returned |
| D | CrewAI `GroqCompatibleLLM.call(..., response_model=Minimal)` | **PASS**; structured response returned |
| E | Current Researcher task, native Coraxis tools, adapter | **FAIL**; model emitted synthetic `json` call and Groq rejected it |
| F | Minimal CrewAI agent, valid local tool schema, adapter, `output_json=Minimal` | **FAIL**; model emitted undeclared `JSON` call |
| G | Minimal CrewAI agent, no tools, adapter, `output_json=Minimal` | **PASS**; structured JSON response returned |
| H | Direct current model, JSON mode plus one declared function tool | **FAIL**; Groq says JSON mode cannot be combined with tools |
| I | Direct `groq/openai/gpt-oss-20b`, one declared function tool | **PASS**; declared `echo` call returned |
| J | Direct `groq/openai/gpt-oss-20b`, JSON mode without tools | **FAIL**; Groq returned JSON validation failure with empty generated output |
| K | Direct `groq/llama-3.3-70b-versatile` checks | **NOT VERIFIED**; Groq reported model not found or unavailable |

Experiment F initially also exposed an invalid empty local-tool schema. After
correcting the diagnostic tool to include a valid Pydantic argument schema, the
experiment reproduced the undeclared `JSON` failure. This confirms that the
failure is not caused by the local tool schema.

## 5. Root cause

### Established facts

The immediate root cause is **model-generated structured-output tool calling
inside a CrewAI native-tool request where the generated tool is not declared**.

The failure is not caused by:

- the `cache_breakpoint` adapter;
- missing Groq authentication;
- LiteLLM's direct function-tool support;
- the Coraxis tool names;
- MCP;
- the Pydantic `SubQuestions` model alone;
- JSON mode alone.

### Responsibility boundary

The failure is an integration incompatibility between:

- CrewAI 1.15.37's native-tool path and `output_json` semantics;
- the GPT-OSS model's behavior when asked for structured JSON alongside tools;
- Groq's strict validation of declared tool names and tool arguments.

LiteLLM forwards the native request and maps Groq's error. Coraxis supplies the
task schema and tools but does not create the synthetic `json` tool.

## 6. Conflicting request parameters

The failing Researcher request does **not** contain an incompatible
`response_format` field. The relevant request state is:

```text
tools: six declared Coraxis tools
tool_choice: absent/null
response_format: absent/null
```

The conflict is semantic rather than a literal simultaneous
`tools + response_format` conflict: the prompt requests JSON structured output,
while the active native-tool protocol permits the model to emit tool calls.
The model chooses a tool name that is not declared.

A direct test confirms that explicitly sending both `tools` and
`response_format={"type":"json_object"}` is rejected by Groq:

```text
json mode cannot be combined with tool/function calling
```

## 7. Model compatibility findings

### Current model: `groq/openai/gpt-oss-120b`

Verified live behavior:

- direct JSON mode without tools: succeeds;
- direct declared function call: succeeds;
- CrewAI structured output without native tools: succeeds;
- CrewAI native tools plus structured task output: emits undeclared `json`/`JSON`
  calls and fails.

### `groq/openai/gpt-oss-20b`

Verified live behavior:

- direct declared function call: succeeds;
- direct JSON mode without tools: failed JSON validation in this run.

This model was not substituted into Coraxis and was not used for benchmarking.

### `groq/llama-3.3-70b-versatile`

Not verified because Groq reported that the model did not exist or was not
available to the configured account.

The available evidence does not establish that changing models alone resolves
the CrewAI integration issue.

## 8. Candidate solutions and trade-offs

### Option A: Add JSON mode while retaining Researcher tools

**Recommendation:** Reject.

Groq explicitly rejects `response_format=json_object` together with function
tools. This would preserve neither the existing Researcher tool behavior nor
Groq compatibility.

### Option B: Prompt the model not to call a JSON tool

**Recommendation:** Not sufficient as a permanent fix.

It may reduce the failure rate, but the live model already ignored the
implicit distinction between JSON output and native tools. Prompt-only
behavior is not a reliable protocol boundary.

### Option C: Disable all Researcher tools for Groq structured tasks

**Recommendation:** Reject as a broad fix.

This could make JSON mode work, but it would remove `recall_memory`,
`web_search`, and collaboration capabilities from the Researcher and would
change the product behavior.

### Option D: Split tool use and structured output into separate calls

**Recommendation:** Strong candidate.

Use a native-tool phase for Researcher actions, then make a second no-tools
structured-output call using JSON mode or CrewAI's Pydantic path. This respects
Groq's protocol limitation and preserves tools, but requires an explicit
two-phase orchestration boundary and careful transfer of tool results.

- Public/private API: can be implemented through existing CrewAI task and LLM
  boundaries, but exact orchestration hooks require validation.
- Sync/async: implement both paths and test both.
- Upgrade risk: moderate; avoid relying on undocumented global state.
- External contract: can preserve `SubQuestions` if the final parser validates
  the second call.
- MCP/tools: preserved during the first phase.

### Option E: Use a declared structured-output function tool

**Recommendation:** Candidate, requiring live validation.

Declare a real tool such as `emit_subquestions` whose schema is the
`SubQuestions` contract, while retaining the Researcher tools. The executor
would accept that declared tool and convert its arguments into `SubQuestions`.
This avoids the undeclared `json` name, but GPT-OSS must reliably select the
declared tool and produce valid arguments. The current evidence proves direct
declared function calling works, but does not yet prove this full CrewAI
integration.

- Public/private API: likely uses CrewAI native tool APIs; conversion logic must
  be Coraxis-owned.
- Sync/async: test both.
- Upgrade risk: moderate.
- External contract: preservable.
- MCP/tools: preserved.

### Option F: Use a separate function-calling LLM

**Recommendation:** Conditional candidate.

CrewAI exposes `function_calling_llm`, but its deprecation status and
interaction with `output_json` must be verified for this exact release. A
separate LLM could handle tool calls while a no-tools LLM handles structured
output, but it introduces more configuration and cost.

- Public/private API: CrewAI exposes the field, but the field is marked
  deprecated in the installed version.
- Sync/async: requires separate tests.
- Upgrade risk: high to moderate because of deprecation.
- External contract: potentially preservable.

### Option G: Provider-specific adapter that rewrites undeclared JSON calls

**Recommendation:** Do not use as the first solution.

Rewriting a provider response after Groq rejects it is too late. Rewriting
request tools to add a synthetic JSON tool would require changing the native
tool contract and could hide model/tool protocol errors. It would also be more
fragile than separating the two protocols.

## 9. Recommended solution

The safest direction is a **Groq-specific two-protocol orchestration path**:

1. Preserve the existing native Coraxis tools for Researcher actions.
2. Do not request Pydantic/JSON structured output in the same native-tool call.
3. After tool use completes, issue a separate no-tools structured-output call
   using the existing `SubQuestions` schema.
4. Validate the returned JSON with Pydantic before passing it to Web Searcher.
5. Keep the existing Groq `cache_breakpoint` adapter for message sanitization.
6. Leave non-Groq providers on the current behavior unless their own tests
   require a change.

This recommendation preserves MCP and tool functionality, avoids deleting
unrelated tools, respects Groq's prohibition on JSON mode plus tools, and
creates a clear protocol boundary. A declared `emit_subquestions` tool is a
reasonable alternative if a focused CrewAI experiment proves it reliable, but
it should not be adopted without that evidence.

No fix was implemented in this investigation.

## 10. Files likely to change during implementation

These are expected future changes only:

- [`src/coraxis/agents/tasks.py`](src/coraxis/agents/tasks.py) — separate
  Researcher tool work from structured `SubQuestions` conversion.
- [`src/coraxis/agents/crew.py`](src/coraxis/agents/crew.py) — if an explicit
  two-phase task/crew boundary is needed.
- [`src/coraxis/services/llm/groq_compat.py`](src/coraxis/services/llm/groq_compat.py)
  — only if the approved design needs a narrowly scoped structured-output
  helper; the cache-marker behavior should remain unchanged.
- [`tests/unit/test_groq_compatibility.py`](tests/unit/test_groq_compatibility.py)
  — request-preservation and provider-boundary regression coverage.
- A new focused test module for structured-output/tool protocol separation.
- A new isolated live diagnostic test or script, kept separate from normal CI.

Dependency manifests should not change based on this investigation.

## 11. Deterministic regression test plan

Before any implementation is approved, add tests for:

1. Researcher tool schemas contain exactly the expected declared names.
2. Researcher native-tool requests do not include a synthetic `json` or `JSON`
   tool.
3. Groq structured-output calls contain no native tools.
4. Groq JSON mode is never combined with function tools.
5. `SubQuestions` validates the structured response and rejects malformed JSON.
6. Tool results are transferred intact into the structured-output phase.
7. MCP and Coraxis tool interfaces remain unchanged.
8. Non-Groq providers retain their current task behavior.
9. Synchronous two-phase execution works.
10. Asynchronous two-phase execution works.
11. Concurrent executions do not share mutable request state.
12. The existing cache-marker adapter still removes only `cache_breakpoint`.
13. A minimal declared `emit_subquestions` tool, if selected, is tested with
    valid and invalid model arguments.

Live integration tests should separately verify:

- current `gpt-oss-120b` direct JSON mode;
- current model direct declared tool calling;
- approved CrewAI orchestration;
- one real local tool execution;
- no secret values in captured schemas or logs.

## 12. Remaining uncertainties

The following were not established and require approval before implementation:

1. Whether CrewAI 1.15.37 exposes a stable public hook for splitting native
   tool execution from final structured conversion.
2. Whether a declared `emit_subquestions` tool is consistently selected by
   `gpt-oss-120b` in the full Researcher prompt.
3. Whether a separate `function_calling_llm` remains reliable despite its
   deprecation marker.
4. Whether a newer compatible CrewAI release changes this behavior without
   reintroducing the MCP or `cache_breakpoint` issues.
5. Whether the exact two-phase orchestration can preserve all current retries,
   event capture, token accounting, and persistence semantics.

## 13. Preservation and stop confirmation

- Application code: **not modified**.
- Dependency manifests and lockfiles: **not modified**.
- Existing Groq cache adapter: **preserved**.
- Phase 02A baseline: **preserved**.
- Existing benchmark results and reports: **not modified**.
- Ten-case benchmark: **not rerun**.
- Database migrations: **not modified**.
- Commit, push, reset, clean, stash, discard: **none**.
- API keys and authorization headers: **not exposed**.
