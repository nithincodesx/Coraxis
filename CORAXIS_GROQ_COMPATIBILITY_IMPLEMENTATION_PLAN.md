# Coraxis Groq Compatibility Adapter — Implementation Plan

## 1. Executive summary

This is a planning document only. No application code, dependency manifest,
lockfile, baseline record, existing report, environment variable, or API key
was changed. The Phase 02F ten-case benchmark was not run.

The failure is caused by CrewAI 1.15.37 adding `cache_breakpoint=True` to
message dictionaries before calling LiteLLM. Groq rejects that nested property.
LiteLLM's `drop_params=True` does not recursively remove keys from message
dictionaries.

The recommended future design is a **Coraxis-owned, instance-local Groq LLM
adapter**:

1. Keep CrewAI, LiteLLM, MCP, tools, and the four-agent pipeline intact.
2. Construct a Groq-specific `LLM` subclass or equivalent CrewAI LLM boundary
   object in `build_llm`.
3. Override the narrow message-preparation boundary to copy only the message
   dictionaries and remove only `cache_breakpoint` for Groq.
4. Leave all other providers on the existing CrewAI `LLM` path.
5. Do not patch `litellm.completion`, `litellm.acompletion`, CrewAI modules, or
   global hook registries.

This is the narrowest approach identified that preserves synchronous and
asynchronous CrewAI calls, tool calls, tool responses, concurrency isolation,
and provider selection. It still relies on a **private CrewAI method**
(`LLM._prepare_completion_params`) because the tested CrewAI release does not
expose a public provider-specific message-transform hook. That limitation must
be accepted explicitly or resolved upstream before implementation.

## 2. Preflight record

### Git state

| Item | Observed value |
|---|---|
| Branch | `main` |
| HEAD | `0e008a2` (`docs: add PHASE_01_5_VERIFICATION_REPORT.md`) |
| Remote relation | Existing reports state `origin/main` was in sync |
| Worktree | Uncommitted Phase 02A–02F work and reports |
| Commits/pushes during this task | None |

The worktree already contained modified and untracked files before this plan
was written. Those files were preserved. In particular, the existing
untracked `src/coraxis/services/llm/sanitizer.py` was read but not modified.

### Phase reports and baseline

The Phase 02A–02E reports document the evaluation framework, researcher,
search/source, synthesis, and report-quality changes. Phase 02F documents that
the original ten-case baseline is preserved and that live evaluation was
blocked first by the `CacheableResult` import issue and then by the
`cache_breakpoint` Groq rejection.

The original Phase 02A baseline remains under `evaluation/baseline/`. The
reports consistently state that it must remain untouched. No benchmark case
was executed for this planning task.

## 3. Existing architecture findings

### LLM construction and provider selection

`src/coraxis/services/llm/factory.py` defines the frozen `LLMConfig`, formats
provider/model strings, validates keys, and constructs `crewai.LLM`. The
provider set is `groq`, `gemini`, `openai`, `ollama`, and `custom`.

`build_llm()` currently calls `apply_litellm_patches()` before constructing
every provider's LLM. `validate_provider_key()` calls it before every direct
LiteLLM credential check. Consequently, the current sanitizer is not limited
to CrewAI Groq agent execution.

`src/coraxis/agents/crew.py` constructs each CrewAI `Agent` with the LLM
returned by `build_llm()`, attaches registered Coraxis tools, and assembles
both the sequential four-agent pipeline and user-composed teams.

The built-in pipeline remains:

`Researcher -> Web Searcher -> Synthesis Analyst -> Report Writer`

### Tools and MCP

`src/coraxis/agents/tool_registry.py` registers Coraxis `BaseTool` instances
for search, fetching, memory, claims, messaging, and blackboard operations.
`src/coraxis/agents/tools/crew_tools.py` implements the tools as Pydantic
CrewAI tools with async `_arun()` methods and a deliberate synchronous bridge.
The tool schemas do not contain or depend on `cache_breakpoint`.

`mcp_config.json` registers the local AAS Core and browser MCP servers. The
Coraxis tools are regular CrewAI tools rather than MCP tools, but the
CrewAI/LiteLLM/MCP import compatibility must remain intact. No solution should
override CrewAI's declared `mcp<2,>=1.30.0` constraint.

### Existing tests

The current tests cover tool construction/context identity, async/sync tool
behavior, provider discovery, credentials, report parsing, evaluation
schemas, and run lifecycle. There is no focused unit suite for
`sanitizer.py`, `build_llm()` provider-specific message transformation, or
CrewAI LLM message preparation. Those are required before implementation is
considered complete.

## 4. Existing sanitizer findings

The full current file is
`src/coraxis/services/llm/sanitizer.py`.

### Why it was introduced

Its module docstring identifies two goals:

1. Remove `cache_breakpoint`/`cache_control` message keys that some adapters
   add and that Groq rejects.
2. Retry retired Groq model IDs using `GROQ_FALLBACK_MODELS`.

The repository also contains an older, separate global implementation in
`legacy/utils/llm_factory.py`. It patches LiteLLM at import time and uses older
fallback model IDs. It is not imported by the active `src/coraxis` path, but it
confirms that the global-patch pattern predates the current sanitizer.

### Objects and functions wrapped

`apply_litellm_patches()`:

- sets the module-level `litellm.drop_params = True`;
- captures `litellm.completion`;
- replaces it with `completion_with_fallback`;
- captures `litellm.acompletion`;
- replaces it with `acompletion_with_fallback`;
- applies `clean_messages()` to any `messages` keyword argument;
- retries `litellm.NotFoundError` through `_retry_with_fallback()` or
  `_aretry_with_fallback()`.

`clean_messages()` returns a new top-level list and new dictionaries for
dictionary messages. It removes both `cache_breakpoint` and `cache_control`,
not only the required Groq marker. It does not recursively traverse nested
objects or content blocks.

### Scope and risks

The patch is process-wide. Once installed, every caller of LiteLLM's sync or
async completion functions sees the wrapper, including direct LiteLLM calls
outside CrewAI and all providers, not only Groq. The `_patched` flag and
`_patch_lock` make installation approximately idempotent, but the replacement
of global functions remains shared mutable process state.

Specific risks:

- **Provider scope:** message metadata is stripped for Gemini, OpenAI, Ollama,
  custom providers, and direct LiteLLM callers as well as Groq.
- **Behavior scope:** `cache_control` is removed in addition to
  `cache_breakpoint`; this is broader than the required behavior and may
  affect providers that understand it.
- **Initialization order:** importing or calling a factory/validation path
  changes LiteLLM functions for the rest of the process.
- **Multiple wrappers:** another library or test may wrap LiteLLM before or
  after this patch; the captured “original” function can then be another
  wrapper, complicating call order and rollback.
- **Concurrency:** the wrappers themselves do not use per-request mutable
  state, but global replacement and global `litellm.drop_params` affect
  concurrent calls from unrelated providers.
- **Fallback behavior:** `_is_missing_model_error()` returns true for any model
  string containing `groq`, so any Groq `NotFoundError` enters fallback logic.
  The fallback retry catches broad exceptions while trying candidates.
- **Testability:** `reset_patch_state()` resets only the flag; it does not
  restore the original LiteLLM functions or the prior `litellm.drop_params`
  value. It is explicitly test-oriented and not a complete rollback.

The sanitizer supports both sync and async LiteLLM calls and avoids mutating
the original top-level message list/dictionaries in the common flat-message
case. It does not guarantee deep immutability and affects direct calls
outside CrewAI.

**Conclusion:** the current sanitizer is not a safe permanent
provider-specific adapter. It must not be copied into a new integration point
unchanged. This planning task does not modify it.

## 5. Root-cause recap and verified behavior

In the isolated environment with Python 3.11.9, CrewAI 1.15.37, LiteLLM
1.105.7, and MCP 1.30.0:

1. CrewAI `AgentExecutor._setup_messages()` calls
   `crewai.llms.cache.mark_cache_breakpoint()` for system/user messages.
2. `mark_cache_breakpoint()` returns a new dictionary with
   `cache_breakpoint=True`.
3. CrewAI's non-Anthropic message formatter returns those dictionaries without
   removing the marker.
4. CrewAI's `_prepare_completion_params()` forwards the messages to LiteLLM.
5. CrewAI calls `litellm.completion()` or `litellm.acompletion()`.
6. Groq rejects `messages.0.cache_breakpoint`.

The following are verified from source inspection and real isolated calls:

- `drop_params=True` does not remove this nested message property.
- LiteLLM `additional_drop_params` targeting
  `messages.0.cache_breakpoint` did not remove it in the tested path.
- Direct clean-message completion and function-tool calling succeed.
- CrewAI construction succeeds.
- A test-only marker-removal adapter allowed a real CrewAI kickoff, local
  `BaseTool` execution, and a final response.
- Alternate tested Groq models produced the same schema rejection.

## 6. Candidate integration points

| Candidate | API status | Sync/async | Groq-only | Tool preservation | Concurrency/upgrades | Assessment |
|---|---|---|---|---|---|---|
| CrewAI provider-specific adapter | No stable public registration point verified; provider classes are internal implementation | Potentially both if provider owns both paths | Yes in principle | Yes if it delegates normally | Upgrade-sensitive | Not available as a supported Coraxis integration today |
| CrewAI `before_llm_call` hook | Public hook surface in tested release; context exposes mutable message list | Hook runs for both call styles in the tested architecture | Conditional on `context.llm` | Likely, if only metadata is removed | Global hook registry; mutates executor state; upgrade risk | Narrower than LiteLLM patch, but fails the no-original-mutation requirement |
| Custom `BaseLLM` implementation | CrewAI's documented extension direction; abstract `call()` is public | Must implement both `call()` and `acall()` correctly | Yes | Possible, but must preserve full tool/response protocol | Instance-local but substantial maintenance | Public boundary, high implementation and regression cost |
| `LLM` subclass overriding `_prepare_completion_params()` | Uses CrewAI model type but overrides a private method | Both sync/async paths use preparation in tested release | Yes by selecting subclass only for Groq | Yes; delegates to normal LiteLLM/tool handling | Instance-local; private-method upgrade risk | Recommended short-term design with explicit private-API caveat |
| LiteLLM global completion wrapper | Private/global mutation | Both possible | Not safely; current wrapper affects all providers | Usually, but broad behavior changes | Process-wide state and wrapper ordering risk | Reject as permanent solution |
| LiteLLM provider transformation | LiteLLM internal provider implementation | Depends on provider path | Provider-specific in theory | Could preserve protocol | Requires upstream/internal maintenance; not Coraxis-owned | Not a safe application-level change |

### Candidate details

#### CrewAI provider-specific adapter

CrewAI 1.15.37 has provider implementation classes, but no verified public
configuration that registers a custom message sanitizer for the LiteLLM/Groq
route. Editing or monkey-patching those classes would be private and would
couple Coraxis to CrewAI internals. It is not recommended.

#### CrewAI hooks

`LLMCallHookContext` documents access to a mutable `messages` list and says
hooks should modify it in place rather than replace the list. A hook could
identify a Groq LLM and remove `cache_breakpoint` from each dictionary.
However:

- it mutates the executor's message objects;
- the hook registry is process-global;
- it affects conversation history, not only the outgoing request;
- it must be carefully registered and filtered for direct/non-CrewAI calls;
- it does not satisfy the requirement to avoid mutating original message
  objects.

It is a viable diagnostic experiment, not the recommended implementation.

#### Custom `BaseLLM`

This is the cleanest public abstraction, but implementing it would duplicate
or re-host CrewAI's LiteLLM request preparation, streaming, response parsing,
structured output, retries, tool-call handling, and async behavior. That
surface is too large for a minimal compatibility adapter and creates more
upgrade risk than the current defect.

#### `LLM` subclass

The tested CrewAI source uses `_prepare_completion_params()` for sync,
async, token-count, and related paths. A Groq-only subclass can call
`super()`, copy the returned message list and each dictionary, remove only
`cache_breakpoint`, and return the rest unchanged. This preserves CrewAI's
normal LiteLLM/tool protocol and avoids process-global state.

This is still a private method override. It must be protected by version-pinned
tests and a clear compatibility guard; if a future CrewAI release changes the
method shape, construction should fail clearly rather than silently sending
the marker.

## 7. Recommended future approach

### Design

Introduce a Coraxis-owned `GroqCompatibleLLM` (name illustrative) that is
selected only when `LLMConfig.provider == "groq"`. It should:

1. Reuse CrewAI's normal `LLM` behavior.
2. Override the narrow message-preparation boundary.
3. Deep-copy only the message container needed for the request, without
   mutating the caller's list or dictionaries.
4. Remove exactly `cache_breakpoint` from each top-level message dictionary.
5. Preserve every other key and value, including role, content, tool calls,
   tool-call IDs, function names, ordering, and unrelated metadata.
6. Leave nested content metadata untouched unless a tested Groq request shape
   proves the marker can occur there; do not delete unrelated nested fields.
7. Cover both sync and async paths through the shared preparation method.

The implementation must not reuse `clean_messages()` unchanged because that
function also removes `cache_control` and is currently provider-agnostic.

### Why this approach

- Provider selection occurs naturally in the existing `build_llm()` boundary.
- Each LLM instance carries its own behavior; no global LiteLLM replacement or
  mutable registry is needed.
- Non-Groq LLM instances are constructed exactly as before.
- CrewAI's standard tool execution, MCP imports, function calling, response
  parsing, and retry behavior remain in control.
- Concurrent crews cannot change one another's provider behavior.

### Public versus private API assessment

The adapter's **selection point** (`build_llm`, `LLM` construction, and
`BaseLLM`-compatible object) is Coraxis-owned and stable. The
message-preparation override is **private CrewAI API** because it overrides
`_prepare_completion_params()`. No fully supported public API for this exact
provider-specific transformation was verified in CrewAI 1.15.37.

The plan must therefore:

- state the CrewAI version range it supports;
- add a source-shape/contract test for the overridden method;
- fail explicitly if the expected method is absent or incompatible;
- monitor CrewAI release notes/issues for an upstream public hook;
- remove the private override when CrewAI exposes a supported transformer.

No process-wide monkey patch should be used as the permanent solution.

## 8. Required behavior assessment

| Requirement | Achievable with recommended design? | Verification |
|---|---|---|
| Remove only `cache_breakpoint` for Groq | Yes | Exact-key unit tests and captured outgoing request |
| Preserve roles/content/tool metadata/order | Yes | Structural deep-equality assertions excluding one key |
| Preserve unrelated metadata | Yes | Sentinel metadata tests |
| Non-Groq providers unchanged | Yes | Same-input structural equality and provider construction tests |
| Avoid mutating original objects | Yes | Deep-copy/original snapshot tests |
| Multiple messages | Yes | System/user/history/tool-message fixture |
| Nested request structures | Partially; top-level message dictionaries are the verified CrewAI shape | Fixture with nested content and unrelated nested fields; do not recursively strip without evidence |
| Sync execution | Yes | CrewAI sync kickoff with a local tool and a recording transport |
| Async execution | Yes | `kickoff_async()` and async direct LLM path |
| No global mutable state | Yes | Instance-only adapter; import/reload/concurrency tests |
| Preserve CrewAI tools | Yes | Local `BaseTool` execution and tool-result follow-up |
| Preserve MCP integration | Expected, not yet live-verified after adapter | MCP import/interface smoke tests |
| Avoid secret/sensitive logging | Yes | Logging capture asserting no key/header/content leakage |

The “nested request structures” requirement needs an explicit boundary:
CrewAI's verified failing shape is `messages[*]["cache_breakpoint"]`. The
adapter should sanitize only that documented/observed top-level message key.
Recursive deletion of every matching key in arbitrary content would be broader
and could corrupt provider-specific content.

## 9. Dependency recommendation

The tested compatibility combination is:

| Component | Version |
|---|---:|
| Python | 3.11.9 |
| CrewAI | 1.15.37 |
| LiteLLM | 1.105.7 |
| MCP | 1.30.0 |

LiteLLM 1.105.7 removes the `CacheableResult` import failure observed with
LiteLLM 1.108.3 and MCP 1.30.0. It does **not** solve `cache_breakpoint`.
CrewAI's declared `mcp<2,>=1.30.0` constraint must not be bypassed.

Current manifests declare:

- `pyproject.toml`: `crewai>=0.80`, `litellm>=1.40`
- `requirements.txt`: `crewai>=0.80`, `litellm>=1.40`

Because these lower bounds allow LiteLLM 1.108.3 or later, a fresh install can
reintroduce the `CacheableResult` incompatibility. For a future approved
compatibility release, pinning `litellm==1.105.7` in both manifests is the
lowest-risk dependency action supported by the completed isolated test. It
should be accompanied by a normal dependency-resolution check and provider
regression suite. Do not use `--ignore-requires`, install MCP 2.x against the
CrewAI bound, or alter third-party metadata.

This plan does not edit either manifest and does not install anything into the
main environment.

## 10. Detailed test plan

### Deterministic unit tests — no network or credentials

Create a focused test module, likely
`tests/unit/test_groq_compatibility.py`, covering:

1. A Groq message with `cache_breakpoint` loses exactly that key.
2. A non-Groq message fixture is structurally identical before and after the
   adapter.
3. The input list and every original message dictionary remain unchanged.
4. Roles and string/list content are preserved.
5. Assistant tool calls preserve IDs, function names, arguments, and order.
6. Tool response messages preserve `tool_call_id`, role, and content.
7. Multiple system/user/assistant/tool messages are all handled.
8. Unrelated top-level and nested metadata remains present.
9. A non-dictionary message-like value is preserved or rejected according to
   the existing CrewAI contract; it must not be silently rewritten.
10. Only the exact top-level `cache_breakpoint` key is removed; no recursive
    deletion of unrelated content metadata occurs.
11. Two adapter instances used concurrently do not share mutable message
    state.
12. Non-Groq `build_llm()` returns the normal CrewAI LLM path.
13. Groq `build_llm()` returns the adapter path without changing global
    LiteLLM functions or `litellm.drop_params` beyond existing approved
    behavior.
14. No API key, authorization header, message content, or request payload is
    emitted by adapter logging.

Use immutable snapshots/deep copies and a fake or recording completion boundary
for request-shape assertions. Do not assert against mocks alone for the final
behavior; the recording boundary is for deterministic shape tests only.

### CrewAI integration tests — isolated, preferably no network first

1. Import CrewAI, LiteLLM, MCP, and the adapter.
2. Construct a CrewAI `Agent`, `Crew`, `Task`, and local Coraxis-style
   `BaseTool`.
3. Execute a sync kickoff through a recording/fake provider only if the
   repository's test architecture supports such a boundary.
4. Execute an async kickoff path.
5. Verify the local tool runs and its result is included in the subsequent
   agent conversation.
6. Verify tool-call messages and tool responses retain their metadata.
7. Build all registered Coraxis tools and assert their context identity and
   schemas remain unchanged.
8. Import the configured MCP integration and verify the existing MCP-bound
   imports; do not bypass dependency constraints.

If CrewAI cannot be cleanly faked at the LLM transport boundary, keep these
tests as isolated live tests rather than weakening unit tests with broad mocks.

### Real Groq tests — credentials required, isolated environment only

Run only after deterministic tests pass:

1. One clean direct completion.
2. One direct function-tool call.
3. One CrewAI sync kickoff with a local `BaseTool`.
4. One CrewAI async kickoff with a local `BaseTool`.
5. Capture only sanitized request-shape metadata; never capture keys,
   authorization headers, or prompt content in logs/artifacts.
6. Confirm Groq receives no `cache_breakpoint` while roles/content/tool
   metadata remain valid.
7. Confirm a non-Groq provider smoke test is unchanged in its own isolated
   environment or with a deterministic provider boundary.

These are not benchmark cases. They are compatibility smoke tests and should
be run before any benchmark approval.

### Concurrency test

Run concurrent Groq-adapter and non-Groq-adapter calls using separate
instances and recording boundaries. Assert:

- Groq requests are sanitized;
- non-Groq requests retain their input;
- no request observes another request's model/provider behavior;
- no global LiteLLM function identity changes;
- original message objects remain unchanged.

## 11. Benchmark readiness gate

Before retrying the original ten Phase 02F cases, all of the following must be
true:

1. A future implementation is explicitly approved and applied.
2. The isolated package combination imports cleanly:
   CrewAI 1.15.37, LiteLLM 1.105.7, MCP 1.30.0, Python 3.11.9.
3. Deterministic adapter tests pass.
4. Sync and async real Groq smoke tests pass.
5. Real CrewAI local-tool execution passes, including tool result handling.
6. MCP imports and all registered Coraxis tool-interface tests pass.
7. Non-Groq provider smoke tests pass.
8. The four-agent crew constructs successfully.
9. The original `evaluation/baseline/` directory is unchanged.
10. New Phase 02F results use a separate output directory and do not overwrite
    Phase 02A records.
11. No benchmark result is reported unless the corresponding case completed
    with real LLM execution.

The ten-case benchmark must remain a separate, explicitly approved action. It
was not run here.

## 12. Exact files likely to change in a future implementation

These are prospective files only; none were changed by this plan:

1. `src/coraxis/services/llm/sanitizer.py`
   - Refactor the current process-wide behavior into a pure, Groq-scoped
     message transformation and/or isolate model fallback behavior.
   - Do not retain broad removal of `cache_control` for all providers.
2. `src/coraxis/services/llm/factory.py`
   - Select the Groq-compatible LLM instance only for `provider="groq"`.
3. A new adapter module, likely
   `src/coraxis/services/llm/groq_compat.py`
   - Own the instance-local subclass and copy-on-write message preparation.
4. `src/coraxis/services/llm/__init__.py`
   - Export the adapter only if it is part of the intentional internal/public
     service surface.
5. `pyproject.toml`
   - Future approved pin for `litellm==1.105.7`; possibly an explicit tested
     CrewAI version constraint.
6. `requirements.txt`
   - Keep the operational requirements file aligned with the approved pin.
7. New focused tests, likely
   `tests/unit/test_groq_compatibility.py`.
8. Possibly `tests/integration/test_llm_compatibility.py`
   - Only for isolated/live smoke tests; no benchmark records belong here.

Files that should **not** be changed for the adapter:

- `src/coraxis/agents/tasks.py`
- `src/coraxis/agents/crew.py` (unless construction wiring cannot remain in the
  LLM factory)
- `src/coraxis/agents/tools/crew_tools.py`
- MCP configuration
- `evaluation/baseline/*`
- Phase 02A–02F reports

## 13. Estimated implementation sequence

1. Obtain approval for this plan and resolve the private-API acceptance
   question.
2. Freeze the isolated test environment at the already tested versions without
   touching the main environment.
3. Add deterministic copy-on-write message transformation tests first.
4. Implement the adapter in a new module, keeping the existing sanitizer
   untouched until equivalent tests cover its required fallback behavior.
5. Wire Groq-only selection in `factory.py`.
6. Decide separately whether the existing Groq model-fallback behavior should
   be migrated into the instance-local adapter or left as a separately
   approved change. Do not silently combine unrelated fallback behavior with
   marker removal.
7. Run unit, lint, type, import, tool, and MCP smoke tests.
8. Run isolated real Groq completion, function-tool, sync kickoff, and async
   kickoff tests.
9. Run non-Groq regression checks.
10. Pin LiteLLM only in a separate dependency-approved change, if required.
11. Confirm the Phase 02A baseline is unchanged.
12. Request explicit approval before running the ten-case Phase 02F benchmark.

## 14. Risks and rollback

### Risks

- The recommended subclass overrides a private CrewAI method and may require
  revision after a CrewAI upgrade.
- A future CrewAI path may bypass `_prepare_completion_params()`; source-shape
  and real sync/async tests must detect this.
- Copy-on-write must preserve tool-call and multimodal message structures.
- LiteLLM 1.105.7 is older than the currently installed 1.108.3 and may lack
  later fixes; provider regression testing is required.
- Separately migrating the existing model fallback can introduce retries,
  quota use, or error masking if not tested independently.
- Groq model availability and rate limits are external and time-sensitive.

### Rollback

Because the proposed adapter is instance-selected, rollback should be:

1. Stop constructing the Groq adapter in `factory.py`.
2. Restore normal `crewai.LLM` construction.
3. Restore the previously approved dependency pin or remove only the approved
   pin change.
4. Do not use `git reset`, `git checkout`, stash, or broad cleanup to roll
   back unrelated work.
5. Re-run import and provider smoke tests, confirming no global LiteLLM
   functions were patched.

If implementation reveals that the private CrewAI method is unstable, the
safe rollback is to remove the adapter rather than fall back to a
process-wide monkey patch.

## 15. Explicit unresolved questions

1. Is a private `_prepare_completion_params()` override acceptable for the
   project, or must implementation wait for a CrewAI public transformer?
2. Should the existing Groq model-fallback behavior be migrated in the same
   change, or handled in a separate approved change?
3. Should `crewai` also be pinned to 1.15.37, or is the project willing to
   validate a newer release before updating the pin?
4. Should LiteLLM be pinned in both `pyproject.toml` and `requirements.txt`
   immediately, or only after the full provider regression suite?
5. Does Coraxis require Anthropic-style `cache_control` behavior in any future
   provider? If yes, broad removal from the current sanitizer must be avoided.
6. Does the deployed runtime use `pyproject.toml`, `requirements.txt`, or
   another lock/build path as the source of truth?
7. Should the adapter support only the tested CrewAI 1.15.x line, with a clear
   startup guard for other versions?
8. Can the repository expose a deterministic transport seam for CrewAI
   integration tests without weakening the real-tool execution test?

## 16. Verification status

### Verified

- Current branch, HEAD, and dirty worktree state.
- Existing sanitizer source and its active call sites.
- Active LLM factory and CrewAI construction path.
- Registered Coraxis tools and MCP configuration.
- Current dependency declarations.
- Phase 02A–02F report claims about baseline preservation and blocked live
  benchmarking.
- Isolated package versions and real compatibility results recorded in the
  existing Groq report.

### Not verified in this planning task

- A working `LLM` subclass implementation.
- CrewAI subclass construction under all current Pydantic validators.
- A public CrewAI provider-specific message transformer.
- Live async kickoff through a future adapter.
- Full non-Groq provider matrix after a future change.
- Any Phase 02F benchmark result.

## 17. Final restriction confirmation

- Planning only: no adapter was implemented.
- No application code was modified.
- No dependency file or lockfile was modified.
- No existing report or Phase 02A baseline was modified.
- No package was installed into the main environment.
- No environment variable or API key was changed or exposed.
- No ten-case benchmark was run.
- No commit, push, reset, clean, stash, or discard occurred.

