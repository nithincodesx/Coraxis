# LITELLM 1.105.7 COMPATIBILITY TEST REPORT

## 1. Objective

Test whether downgrading LiteLLM from 1.108.3 to 1.105.7 resolves the CrewAI/MCP
`ImportError: cannot import name 'CacheableResult' from 'mcp.types'` failure that
blocks the Phase 02F live benchmark, while keeping CrewAI 1.15.37 and MCP 1.30.0
unchanged.

All testing was performed in an **isolated temporary virtual environment**
(`C:\Users\shulk\AppData\Local\Temp\opencode\litellm_test_venv`, Python 3.11.9).
The main Coraxis environment was **not modified**. No dependency files, lock
files, or application code were changed. Nothing was committed or pushed.

## 2. Exact Package Versions (isolated venv)

| Package | Version | Source |
|---|---|---|
| Python | 3.11.9 | environment |
| crewai | 1.15.37 | installed (unchanged from main env) |
| litellm | 1.105.7 | installed (downgraded from 1.108.3 for test) |
| mcp | 1.30.0 | installed (unchanged from main env) |

CrewAI 1.15.37 declares `mcp<2,>=1.30.0`, so mcp 1.30.0 is the only version in
range (mcp versions jump from 1.30.0 directly to 2.0.0).

## 3. Pip Dependency Resolution

Command: `pip install crewai==1.15.37 litellm==1.105.7 mcp==1.30.0`

Result: **resolved and installed without conflicts**. Pip accepted all three
constraints simultaneously; crewai's `mcp<2,>=1.30.0` bound is satisfied by
mcp 1.30.0, and litellm 1.105.7 imposes no conflicting mcp constraint.

No `--ignore-requires` or `--no-deps` was used.

## 4. Test Results

### Test 1 — mcp.types imports (mcp 1.30.0)

| Check | Result |
|---|---|
| `import mcp.types` | OK |
| `mcp.types.CacheableResult` present | **False** (expected — mcp 1.30.0 predates it) |

`CacheableResult` does not exist in mcp 1.30.0. This confirms the original
environment's symptom: anything importing `CacheableResult` from `mcp.types`
fails.

### Test 2 — CrewAI initialization

| Check | Result |
|---|---|
| `from crewai import Agent, Crew, Process, Task, LLM` | OK |

CrewAI 1.15.37 imports cleanly with litellm 1.105.7 + mcp 1.30.0.

### Test 3 — LiteLLM initialization (the critical check)

| Check | Result |
|---|---|
| `import litellm` | OK — **no `CacheableResult` import** |

**This is the fix.** With litellm 1.108.3 (main env), `import litellm` triggers
the experimental MCP server/client modules which unconditionally import
`CacheableResult` from `mcp.types`:
- `litellm/proxy/_experimental/mcp_server/result_conversion.py:18`
- `litellm/proxy/_experimental/mcp_server/catalog.py:20`
- `litellm/experimental_mcp_client/client.py:55`

With litellm 1.105.7, these imports do not exist, so `import litellm` succeeds
even though `mcp.types.CacheableResult` is absent. The original `ImportError` is
resolved.

### Test 4 — Real Groq completion (credential read from `.env` via `ProviderEnvKeys`, never printed)

| Check | Result |
|---|---|
| `litellm.acompletion(groq/...)` | OK — non-empty response |

A one-token completion to `groq/openai/gpt-oss-120b` returned successfully.
Groq accepted the API key (no `invalid_api_key`).

### Test 5 — Real Groq function-tool call

| Check | Result |
|---|---|
| `litellm.acompletion` with `tools=[...]`, `tool_choice="required"` | OK |
| `tool_calls` present | True |
| tool name | `echo` |
| tool args | `{"text":"hello-world"}` |

Groq processed a function-tool call correctly through litellm 1.105.7.

### Test 6 — Minimal CrewAI agent with a local test tool

| Check | Result |
|---|---|
| CrewAI `Agent` + `Crew` + `Task` with a local `BaseTool` | Constructs OK |
| `crew.kickoff()` → Groq LLM | **Auth passes** (key accepted), then Groq returns: |
| | `'messages.0' : for 'role:system' the following must be satisfied[('messages.0' : property 'cache_breakpoint' is unsupported)]` |

Authentication succeeds (Groq accepts the key once `GROQ_API_KEY` is in
`os.environ` — CrewAI reads it from the environment). The failure that remains
is a **separate parameter-compatibility issue**: CrewAI passes
`cache_breakpoint` in system-message metadata (prompt caching), and Groq's API
rejects it as unsupported. This is **not** the `CacheableResult` ImportError and
is **not** caused by the litellm downgrade — it is a CrewAI→Groq
prompt-caching parameter mismatch that would need separate handling (e.g. a
different model, or suppressing `cache_breakpoint`).

### Test 7 — Coraxis tool interfaces compatibility

| Check | Result |
|---|---|
| `issubclass(ContextTool, BaseTool)` | True |
| `issubclass(SearchTool, ContextTool)` | True |
| `SearchTool(context=...)` constructs | OK (`name="web_search"`) |

Coraxis tools remain standard CrewAI `BaseTool` subclasses and construct
normally under litellm 1.105.7. No Coraxis application code changes are needed
for tool-interface compatibility.

## 5. Summary Table

| # | Test | litellm 1.108.3 (main) | litellm 1.105.7 (isolated) |
|---|---|---|---|
| 1 | Pip resolution (crewai+litellm+mcp) | N/A (already installed) | PASS |
| 2 | `mcp.types.CacheableResult` exists | No | No (mcp 1.30.0) |
| 3 | `import litellm` | FAIL (`CacheableResult`) | **PASS** |
| 4 | CrewAI Agent/Crew/Task/LLM import | N/A | PASS |
| 5 | Groq completion via litellm | N/A | PASS |
| 6 | Groq function-tool call via litellm | N/A | PASS |
| 7 | CrewAI agent `kickoff()` with Groq | FAIL (`CacheableResult`) | Auth OK; `cache_breakpoint` param rejected by Groq (separate issue) |
| 8 | Coraxis tool interfaces (BaseTool subclasses) | N/A | PASS |

## 6. Does the downgrade fix the original import failure?

**Yes.** The original failure — `ImportError: cannot import name 'CacheableResult'
from 'mcp.types'` — is caused by litellm 1.108.3's experimental MCP code
importing that symbol unconditionally. litellm 1.105.7 does not contain that
import, so `import litellm` (and therefore CrewAI initialisation via LiteLLM)
succeeds with mcp 1.30.0.

## 7. New Compatibility Risks

- **`cache_breakpoint` parameter**: CrewAI passes `cache_breakpoint` in system
  messages when calling litellm; Groq rejects it as unsupported. This blocks a
  full CrewAI `kickoff()` against Groq even with litellm 1.105.7. It is a
  separate issue from `CacheableResult` and may require:
  - a different Groq model,
  - suppression of `cache_breakpoint`, or
  - a CrewAI/litellm version where `drop_params` strips it for Groq.
  It did **not** affect direct `litellm.acompletion` calls (tests 4–5), only the
  CrewAI agent orchestration path.
- **litellm 1.105.7 is older** than 1.108.3; it may lack later bug fixes or
  provider support. Regression-test against the project's full provider matrix
  (Groq, Gemini, OpenAI, Ollama, custom) before adopting.
- CrewAI still declares `mcp<2`, so mcp 2.x (which has `CacheableResult`) cannot
  be used without overriding CrewAI's bound — not recommended.

## 8. Recommendation for the Main Project

**Option A (recommended for unblocking):** Pin `litellm==1.105.7` in
`pyproject.toml` (replace `litellm>=1.40`) to eliminate the `CacheableResult`
ImportError while keeping `crewai==1.15.37` and `mcp==1.30.0`. Then
investigate the separate `cache_breakpoint` Groq parameter issue (likely a
CrewAI/litellm `drop_params` or model-selection concern) before declaring the
live benchmark fully green.

**Option B:** Wait for CrewAI upstream to relax its `mcp<2` bound so mcp 2.x
(which ships `CacheableResult`) can be used; no published CrewAI version
(≤1.15.39) does so yet.

**Do not** modify pyproject.toml yet — await approval.

## 9. Rollback

Revert `litellm` to 1.108.3 (or remove the pin, restoring `litellm>=1.40`). The
main environment currently still runs litellm 1.108.3; no changes were made to
it.

## 10. Constraints Honored

- Main Coraxis environment: unmodified (crewai 1.15.37, mcp 1.30.0, litellm
  1.108.3).
- `pyproject.toml`, lock files, requirements files, application code: not
  modified.
- No `pip install`/`uninstall`/`upgrade`/`downgrade` in the main environment.
- MCP version: unchanged (1.30.0).
- No `--ignore-requires` or `--no-deps`.
- No API keys or credentials printed or exposed.
- Nothing committed, pushed, reset, stashed, or discarded.

## 11. Test Commands (reproducible)

```bash
# Isolated venv
python -m venv /tmp/litellm_test_venv
/tmp/litellm_test_venv/Scripts/python.exe -m pip install crewai==1.15.37 litellm==1.105.7 mcp==1.30.0

# Verify CacheableResult absent, litellm imports
/tmp/litellm_test_venv/Scripts/python.exe -c "import mcp.types as t; print(hasattr(t,'CacheableResult'))"   # False
/tmp/litellm_test_venv/Scripts/python.exe -c "import litellm; print('litellm OK')"                        # OK

# Verify Groq completion + tool call (set GROQ_API_KEY from .env, do not print)
/tmp/litellm_test_venv/Scripts/python.exe -c "from litellm import acompletion; import asyncio; asyncio.run(acompletion(model='groq/openai/gpt-oss-120b', messages=[{'role':'user','content':'hi'}], api_key='<from .env>', max_tokens=5, drop_params=True))"
```

## 12. Final State

- Main environment: untouched (crewai 1.15.37, litellm 1.108.3, mcp 1.30.0).
- Isolated venv: `C:\Users\shulk\AppData\Local\Temp\opencode\litellm_test_venv`
  (creatable/deletable at will; contains no Coraxis source).
- No files committed or pushed.
