# CREWAI / MCP DEPENDENCY COMPATIBILITY REPORT

## 1. Root Cause

The Phase 02F live benchmark is blocked at CrewAI initialisation by:

```
ImportError: cannot import name 'CacheableResult' from 'mcp.types'
```

The import chain is:

1. **Coraxis pipeline** → `crew.kickoff()` (Researcher → Web Searcher → Synthesis Analyst → Report Writer).
2. **CrewAI 1.15.37** executes agent tools via LiteLLM's native tool-calling listener (`call_llm_native_tools`).
3. **LiteLLM 1.108.3** experimental MCP server/client code imports `CacheableResult` from `mcp.types`:
   - `litellm/proxy/_experimental/mcp_server/result_conversion.py:18`
   - `litellm/proxy/_experimental/mcp_server/catalog.py:20`
   - `litellm/experimental_mcp_client/client.py:55`
4. **mcp 1.30.0** (installed) does **not** export `CacheableResult` in `mcp.types` → `ImportError`.

`CacheableResult` is **not** imported by CrewAI directly; it is imported transitively through LiteLLM's experimental MCP code path, which CrewAI activates whenever it executes tools via LiteLLM — even though Coraxis's pipeline uses DuckDuckGo/fetch tools rather than MCP tools.

## 2. Verified Package Versions

| Package | Installed version | Source |
|---|---|---|
| Python | 3.11.9 | environment |
| crewai | 1.15.37 | `importlib.metadata` |
| crewai (latest on PyPI) | 1.15.39 | `pip index versions` |
| mcp | 1.30.0 | `importlib.metadata` |
| mcp (latest) | 2.3.0 | `pip index versions` / dry-run |
| litellm | 1.108.3 | `importlib.metadata` |
| duckduckgo-search | installed | pyproject dependency |
| trafilatura | installed | pyproject dependency |

## 3. Symbol Availability Across MCP Versions

Verified in an isolated temporary venv (not the main environment):

| MCP version | `mcp.types.CacheableResult` available? | Method |
|---|---|---|
| 1.30.0 (installed) | **No** | `hasattr(mcp.types, 'CacheableResult')` → False; dir() shows no `Cache*` symbols |
| 2.3.0 | **Yes** | `from mcp.types import CacheableResult` succeeded |

So `CacheableResult` was introduced in the **mcp 2.x** line (shipped via `mcp-types` 2.x). No mcp 1.x version provides it (mcp 1.x maxes at 1.30.0; versions jump from 1.30.0 directly to 2.0.0).

## 4. CrewAI's MCP Bound Blocks the Fix

CrewAI declares `mcp<2,>=1.30.0`. Verified for both CrewAI 1.15.37 (installed) and CrewAI 1.15.39 (latest on PyPI) via `pip install --dry-run`:

```
Collecting mcp<2,>=1.30.0 (from crewai==1.15.37)
  Using cached mcp-1.30.0-py3-none-any.whl
```

Critical: even when mcp 2.3.0 was **pre-installed** in the isolated venv, running `pip install crewai==1.15.37` caused pip to **downgrade mcp back to 1.30.0** to satisfy crewai's `<2` upper bound. Pip enforces the bound strictly — crewai + mcp 2.x cannot co-exist through normal dependency resolution.

Therefore **upgrading mcp to 2.x alone is pip-blocked**, and **upgrading CrewAI to 1.15.39 (latest) does not help** — it still caps mcp at `<2`.

## 5. Candidate Compatible Combinations

No combination of currently published CrewAI (≤1.15.39) + mcp satisfies both constraints simultaneously:

| Combination | `CacheableResult` present? | Pip-resolvable? | Verdict |
|---|---|---|---|
| crewai 1.15.37 + mcp 1.30.0 | No | Yes | **Broken** (current state) |
| crewai 1.15.39 + mcp 1.30.0 | No | Yes | Broken |
| crewai 1.15.37 + mcp 2.x | Yes | **No** (pip forces mcp<2) | Blocked by pip |
| crewai 1.15.39 + mcp 2.x | Yes | **No** (pip forces mcp<2) | Blocked by pip |

### Candidate fix A: Downgrade LiteLLM

LiteLLM's `CacheableResult` import lives in its experimental MCP server/client modules. An older litellm (predating those modules) would not import the symbol, keeping crewai + mcp 1.x functional.

- litellm 1.108.3 (installed): imports `CacheableResult` — broken with mcp 1.x.
- litellm ≥1.40 (pyproject minimum): not yet tested for the symbol.
- Attempted `pip download litellm==1.40.0` → version yanked/not found; exact version boundary **not yet determined**.

Status: **candidate, requires version-boundary testing** (which litellm version first imports `CacheableResult`, and whether downgrading litellm breaks crewai's other integrations).

### Candidate fix B: Upgrade mcp to 2.x + relax CrewAI's bound

mcp 2.3.0 provides `CacheableResult`. But CrewAI's `mcp<2` bound is enforced by pip and cannot be satisfied through `pyproject.toml`/`requirements` alone without editing CrewAI's installed metadata or using `--ignore-requires`/`--no-deps`, which is fragile and modifies an installed third-party package.

Status: **candidate, but requires overriding CrewAI's declared bound** (not a clean dependency-file change).

### Candidate fix C: Wait for upstream CrewAI fix

A future CrewAI version could relax `mcp<2` to `mcp>=1.30.0,<3` (or similar) once validated against mcp 2.x. Latest PyPI CrewAI (1.15.39) still caps `<2`, so no published fix yet.

Status: **not available**.

## 6. Compatibility with LiteLLM / Python 3.11 / Coraxis

- Python 3.11.9: no version conflict; all packages install on 3.11.
- LiteLLM 1.108.3: plain completion works (verified — `validate_provider_key` Groq ping returned `valid: True` at 4.58s). The failure is **only** in the MCP tool-calling listener path, which is triggered when CrewAI executes any tool via LiteLLM.
- Coraxis integrations (DuckDuckGo search, httpx fetch, FastAPI, SQLAlchemy, ChromaDB): unaffected by the mcp issue; the failure is isolated to CrewAI→LiteLLM MCP tool dispatch.
- Coraxis `pyproject.toml` declares `crewai>=0.80` (unbounded above) and `litellm>=1.40` (unbounded above), so neither upper bound currently restricts a fix at the project level.

## 7. Test Commands and Actual Results

All run in an isolated temporary venv at `C:\Users\shulk\AppData\Local\Temp\opencode\mcp_test_venv` (not the main environment). No main-environment packages were installed, upgraded, or removed.

```
# 1. Confirm mcp 1.30.0 lacks CacheableResult (installed env, verified)
python -c "import mcp.types as t; print(hasattr(t,'CacheableResult'))"
# → False

# 2. Confirm mcp 2.3.0 provides CacheableResult (isolated venv)
python -m pip install --quiet mcp==2.3.0
python -c "from mcp.types import CacheableResult; print('OK')"
# → OK

# 3. Confirm pip enforces crewai's mcp<2 bound (isolated venv, dry-run)
python -m pip install --dry-run crewai==1.15.37
# → "Collecting mcp<2,>=1.30.0 (from crewai==1.15.37)" then selects mcp-1.30.0,
#    even though mcp 2.3.0 was pre-installed.

# 4. Confirm plain litellm completion works (main env, no credentials printed)
python groq_connect_check.py   # validate_provider_key(groq) → valid=True, 4580 ms
```

## 8. Recommended Dependency Change

**Do not apply yet — awaiting approval.**

Recommended: resolve the crewai/mcp bound conflict by upgrading **mcp to 2.x** (e.g., `mcp>=2.3.0,<3`) and correspondingly relaxing CrewAI's constraint so pip will accept mcp 2.x. Because CrewAI's own metadata hard-caps `mcp<2`, this requires either:

1. Upgrading CrewAI to a version whose `mcp` bound permits 2.x (none published yet — 1.15.39 still caps `<2`), **or**
2. Pinning `mcp>=2` and accepting that CrewAI's declared `<2` bound must be overridden at install time (e.g., `--ignore-requires` or a post-install constraint), with the understanding this is unsupported by CrewAI until upstream relaxes it.

If an older litellm is confirmed to not import `CacheableResult`, **downgrading litellm** (keeping crewai + mcp 1.x) is the lower-risk alternative, but the exact version boundary is undetermined.

## 9. Risks and Rollback Procedure

### Risks

- **mcp 2.x is a major version bump** for the MCP SDK; breaking changes in `mcp.types`/`mcp.client` could affect any direct MCP usage (Coraxis does not currently use MCP tools, but CrewAI/LiteLLM internals do).
- **Overriding CrewAI's `mcp<2` bound** is unsupported by CrewAI; future CrewAI upgrades may reintroduce the conflict or behave unpredictably with mcp 2.x.
- **Downgrading litellm** could break CrewAI's LLM integration or other litellm-dependent features; untested.
- None of these changes alter Coraxis application logic (compliant with the investigation rules).

### Rollback

- Pin the working (pre-change) combination: `crewai==1.15.37`, `mcp==1.30.0`, `litellm==1.108.3` — the state verified to import cleanly but functionally blocked at the MCP listener.
- To roll back an mcp 2.x change: `pip install "mcp==1.30.0"` (crewai's bound will accept it).
- To roll back a litellm change: `pip install "litellm==1.108.3"`.
- No database migrations, application code, or Phase 02A–02F files are touched by this investigation.

## 10. Conclusion

The blocker is an **upstream dependency conflict**: CrewAI caps `mcp<2`, but LiteLLM (pulled in by CrewAI) requires `CacheableResult`, which only exists in mcp 2.x. No published CrewAI version (≤1.15.39) permits mcp 2.x, and pip enforces CrewAI's bound. The benchmark cannot run live until this conflict is resolved — either by CrewAI upstream relaxing the mcp bound, or by a supported install-time override, or by identifying a litellm version that does not import `CacheableResult`.

**No changes were applied to the main environment, no dependency files were modified, no application logic was changed, and no Phase 02A–02F work was altered.** Nothing was committed or pushed.
