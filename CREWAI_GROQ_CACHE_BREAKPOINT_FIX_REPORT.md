# Coraxis CrewAI/Groq `cache_breakpoint` Compatibility Report

## Status

Investigation complete. The main Coraxis environment, dependency manifests, and
application code were not changed by this investigation. Testing used temporary
virtual environments only. No API key or credential value was printed.

## Root cause

CrewAI 1.15.37 adds `cache_breakpoint: true` to the system and user messages
during agent execution. This is a prompt-caching hint, not a required
conversation parameter and not CrewAI's tool-result cache.

The exact path is:

1. `CrewAI AgentExecutor._setup_messages()` imports and calls
   `crewai.llms.cache.mark_cache_breakpoint()` at lines 534-556 of
   `crewai/agents/agent_executor.py`.
2. `mark_cache_breakpoint()` returns a copy with
   `cache_breakpoint=True` at lines 24-31 of `crewai/llms/cache.py`.
3. CrewAI's non-Anthropic `_format_messages_for_provider()` returns the original
   message dictionaries unchanged at lines 2497-2522 of `crewai/llm.py`.
4. `_prepare_completion_params()` forwards those messages to LiteLLM at lines
   765-812 of `crewai/llm.py`.
5. CrewAI calls `litellm.completion()` at line 1349 (and the async equivalent at
   line 1522).
6. LiteLLM sends the message object to Groq. Groq rejects the unknown nested
   property with:

   ```
   messages.0: property 'cache_breakpoint' is unsupported
   ```

`cache_breakpoint` is used by CrewAI's provider-specific prompt-cache handling
(notably Anthropic). Groq's OpenAI-compatible schema does not accept it.

## Exact package versions

Primary isolated environment:

| Component | Version |
|---|---:|
| Python | 3.11.9 |
| CrewAI | 1.15.37 |
| LiteLLM | 1.105.7 |
| MCP | 1.30.0 |
| Groq model | `openai/gpt-oss-120b` |

The LiteLLM 1.105.7 version also resolves the separate
`mcp.types.CacheableResult` import failure. MCP functionality was not removed
or disabled.

## Tests and actual results

All tests below used real Groq requests with the key read from the local
environment without printing it.

| Test | Result |
|---|---|
| `import crewai`, `Agent`, `Crew`, `Task`, `LLM` | PASS |
| `import litellm` | PASS |
| `import mcp` with MCP 1.30.0 | PASS |
| Direct Groq completion with clean messages | PASS |
| Direct Groq function-tool call with clean messages | PASS; tool call `echo` returned |
| Direct completion with `cache_breakpoint` | FAIL; Groq rejects the property |
| Direct completion with `drop_params=True` | FAIL; same Groq rejection |
| Direct completion with `additional_drop_params=["messages.0.cache_breakpoint"]` | FAIL |
| CrewAI `Agent`/`Crew`/`Task` construction | PASS |
| CrewAI kickoff with `drop_params=True` | FAIL; same Groq rejection |
| CrewAI kickoff with nested `additional_drop_params` | FAIL |
| CrewAI kickoff with `gpt-oss-20b` | FAIL; same rejection |
| CrewAI kickoff with `qwen/qwen3.8-27b` | FAIL; same rejection |
| Test-only removal of CrewAI's marker before LiteLLM | PASS; local tool executed and final response returned |

The successful kickoff used the same CrewAI agent/crew/task pattern and a local
`BaseTool`. The tool was invoked (`tool_called=true`) and returned a final
response (`probe`).

## Why `drop_params` does not fix this

CrewAI 1.15.37 sets `litellm.drop_params=True` during LLM initialization
(`crewai/llm.py:727-732`). This controls unsupported top-level LiteLLM/provider
parameters. It does not recursively sanitize arbitrary keys inside
`messages[*]`.

LiteLLM's `additional_drop_params` handling at `litellm/utils.py:5158-5173`
operates on the optional-parameter structure. It did not remove the nested
message key in the real Groq test. Therefore, enabling `drop_params` is not a
valid fix for this failure.

## Solutions investigated

### 1. CrewAI cache configuration

CrewAI's `cache` and `cache_handler` settings control caching of tool results.
They do not control `mark_cache_breakpoint()` in the agent message setup path.
No supported CrewAI setting was found in 1.15.37 to disable this prompt-cache
marker for Groq.

**Result:** Not a fix.

### 2. LiteLLM parameter handling

Tested:

- `drop_params=True`
- global LiteLLM `drop_params=True` behavior already enabled by CrewAI
- `additional_drop_params` targeting `messages.0.cache_breakpoint`

**Result:** Not a fix. The marker is nested in a message, not an unsupported
top-level completion parameter.

### 3. Different Groq models

Tested real CrewAI kickoffs against:

- `groq/openai/gpt-oss-120b`
- `groq/openai/gpt-oss-20b`
- `groq/qwen/qwen3.8-27b`

All returned the same schema rejection before useful agent execution.

**Result:** Model selection does not avoid the incompatibility.

### 4. Removing only the marker

A test-only adapter removed `cache_breakpoint` from the message dictionaries
before the LiteLLM call. With that narrow change:

- CrewAI kickoff completed.
- The local function tool executed.
- A non-empty final response was returned.
- Direct LiteLLM function-tool calling also remained successful.

**Result:** Technically effective, but the test used a monkey patch. A
process-wide monkey patch of CrewAI or LiteLLM is not recommended as the
permanent Coraxis fix because it depends on private implementation details.

### 5. Newer compatible package combination

The previously tested published CrewAI line remains constrained to
`mcp<2,>=1.30.0`; MCP 2.x cannot be installed through normal dependency
resolution with that CrewAI constraint. The relevant failure is independent of
the `CacheableResult` import issue, and changing the MCP line would not remove
CrewAI's message marker. No newer published combination was identified that
provides a supported Groq-specific marker configuration.

## Coraxis pipeline compatibility

Coraxis uses the same CrewAI `LLM` construction for its sequential pipeline:

`Researcher -> Web Searcher -> Synthesis Analyst -> Report Writer`

The marker is generated for every CrewAI agent call, so the failure affects the
whole pipeline rather than one particular Coraxis tool. Removing only this
Groq-incompatible metadata would not remove CrewAI, MCP, function tools, web
search, or report-generation behavior. It would only forgo the prompt-cache
breakpoint hint for Groq calls.

The existing uncommitted compatibility code in
[sanitizer.py](src/coraxis/services/llm/sanitizer.py) is outside this
investigation's changes. It should not be adopted as the permanent solution
without approval because it wraps LiteLLM process-wide.

## Recommendation

Do **not** change Coraxis dependencies or application code yet.

The evidence shows that no supported configuration flag, LiteLLM
`drop_params` option, or tested Groq model fixes the issue. The safe permanent
direction is an upstream-supported provider-boundary change that strips
CrewAI's prompt-cache marker only for providers that reject it, or an upstream
CrewAI release that performs that translation. Until such a change is approved
and tested, do not claim the CrewAI/Groq pipeline is compatible.

The marker-removal test proves that a narrowly scoped provider-boundary adapter
is feasible without disabling tools or MCP, but implementing that adapter would
be an application-code change and is intentionally outside this task.

## Risks

- A process-wide monkey patch can break on CrewAI internal refactors.
- Stripping the marker disables only the prompt-cache hint; it does not provide
  prompt caching to Groq.
- Upgrading MCP to 2.x while CrewAI declares `mcp<2` is unsupported and may
  break CrewAI's MCP integration.
- LiteLLM 1.105.7 is required for the tested `CacheableResult` import
  compatibility, but is older than later LiteLLM releases and should be
  regression-tested before adoption.
- Groq model availability and quotas can change independently of this schema
  issue.

## Rollback instructions

No rollback is required for this investigation because no environment,
dependency file, application code, commit, or configuration was changed.

If a future approved implementation is introduced:

1. Remove only the provider-boundary marker handling.
2. Restore the previously approved CrewAI/LiteLLM/MCP versions.
3. Re-run the import, direct completion, function-tool, and single-crew kickoff
   tests before running any Coraxis benchmark.
4. Confirm that MCP imports and the four-agent pipeline remain enabled.

