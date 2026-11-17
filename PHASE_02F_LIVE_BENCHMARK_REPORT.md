# PHASE 02F LIVE BENCHMARK REPORT

## 1. Executive Summary

Phase 02F live benchmarking **could not be completed** due to an environment
dependency incompatibility that prevents CrewAI from initialising at all.
The Researcher → Web Searcher → Synthesis Analyst → Report Writer pipeline
never executes, so no benchmark cases produced output and no quality metrics
were measured.

A related, separate issue — the evaluation harness could not locate the
Groq API key — was diagnosed and fixed (see §4). After that fix, the
remaining blocker is entirely environmental: CrewAI 1.15.37 requires
`mcp>=1.30.0,<2`, but mcp 1.30.0 (the only version in that range) does not
export `CacheableResult`, which CrewAI imports. No live LLM calls were made.

No credentials were exposed at any point.

## 2. Evaluation Objectives

Per the Phase 02F specification, the live benchmark was intended to measure,
across all 10 Phase 02A benchmark cases:

1. Research question understanding
2. Research decomposition and subquestion quality
3. Search query relevance and diversity
4. Source discovery and source quality
5. URL deduplication and source metadata
6. Evidence extraction and claim traceability
7. Contradiction detection and handling
8. Evidence-strength classification
9. Citation correctness
10. Executive summary quality
11. Final report completeness and readability
12. Research gaps and uncertainty representation

None of these could be measured because the pipeline fails before any agent
executes.

## 3. Repository and Environment Details

| Item | Value |
|---|---|
| Repository | Coraxis 2.0 |
| Branch | `main` |
| HEAD | `0e008a244b7f85645da0a5a78704e0cc2b173842` |
| origin/main | in sync |
| Python | 3.11.9 |
| CrewAI | 1.15.37 |
| MCP SDK | 1.30.0 |
| LiteLLM | installed |
| DuckDuckGo search / Trafilatura | installed |
| Working tree | Uncommitted (Phase 02A–02F + migration hardening + this report) |
| LLM API key | Configured in repo-root `.env` as `GROQ_API_KEY` (not printed) |

## 4. Configuration Verification (Step 1)

### 4.1 Environment-variable detection

| Variable | Detectable? | Source |
|---|---|---|
| `GROQ_API_KEY` | Yes — read via `ProviderEnvKeys` from `.env` | repo-root `.env` |
| `CORAXIS_EVAL_LLM_API_KEY` | No — not set in `os.environ` | — |
| `CORAXIS_EVAL_LLM_PROVIDER` | No — defaults to `"groq"` | — |
| `CORAXIS_EVAL_LLM_MODEL` | No — defaults to `DEFAULT_MODELS["groq"]` | — |

The `.env` file at the repository root contains `GROQ_API_KEY`. Plain
`os.environ` does not auto-load `.env`; only pydantic-settings
(`env_file=".env"`) does, via `Settings.providers.key_for("groq")`.

### 4.2 Provider and model

- Provider: `groq`
- Model resolved: `groq/openai/gpt-oss-120b` (from `DEFAULT_MODELS["groq"]`,
  because `CORAXIS_EVAL_LLM_MODEL` is unset)
- Model connectivity: verified — a 1-token `ping` completed in 4.58s with
  `Valid: True` (credential accepted by Groq). No key material printed.

### 4.3 Minimal API connectivity check

`validate_provider_key(provider="groq", api_key=<from .env>, model="")`
returned `valid=True`. The Groq credential is functional.

### 4.4 Fix applied (benchmark-related, not unrelated refactoring)

The evaluation harness's `_eval_llm_config` (`src/coraxis/evaluation/harness.py`)
read `CORAXIS_EVAL_LLM_API_KEY` directly from `os.environ`, which was empty,
causing `ConfigurationError: groq requires an API key`. The harness now falls
back to `get_settings().providers.key_for(provider)`, which reads the
`GROQ_API_KEY` already configured in `.env` through pydantic-settings
(`env_file=".env"`).

```python
if not api_key.strip():
    from coraxis.core.config import get_settings
    api_key = get_settings().providers.key_for(provider) or ""
```

This is a minimal, benchmark-related addition — the key was already
configured; the harness simply was not consulting it.

## 5. Benchmark Readiness (Step 2)

| Check | Result |
|---|---|
| Original 10 Phase 02A benchmark cases present | Yes — `evaluation/baseline/` |
| Benchmark categories | 8 (comparative, technical, factual, time-sensitive, primary-source, multipart, conflicting, insufficient-evidence) |
| Original baseline preserved | Yes — `evaluation/baseline/` untouched |
| Migration hardening present | Yes — `f531e0c07457` with `server_default` neutral values |
| Phase 02A–02F changes present | Yes — 33 uncommitted entries |
| Benchmark questions modified | No |
| Scoring criteria modified | No |

## 6. Live Benchmark Execution (Step 3) — BLOCKED

All 10 cases were attempted through `EvaluationHarness.run_case`. Every case
failed at CrewAI initialisation before any agent executed:

```
ImportError: cannot import name 'CacheableResult' from 'mcp.types'
```

### Root cause

CrewAI 1.15.37 declares the dependency `mcp<2,>=1.30.0`. The only published
mcp version satisfying that constraint is `1.30.0` (available versions jump
from `1.30.0` directly to `2.0.0`; there is no `1.31–1.x`). However, mcp
`1.30.0` does not export `mcp.types.CacheableResult`, which CrewAI 1.15.37
imports in its MCP tool-listener path (`call_llm_native_tools`). CrewAI
therefore cannot initialise, regardless of API-key configuration.

This is an environment dependency conflict, not a code defect in Coraxis, and
it is unrelated to Phase 02F's report-quality/citation-reliability focus.

### Result per case

| Case | Category | Outcome |
|---|---|---|
| bench-001 | comparative | Blocked — `ImportError: CacheableResult` |
| bench-002 | technical | Blocked — `ImportError: CacheableResult` |
| bench-003 | factual | Blocked — `ImportError: CacheableResult` |
| bench-004 | comparative | Blocked — `ImportError: CacheableResult` |
| bench-005 | time-sensitive | Blocked — `ImportError: CacheableResult` |
| bench-006 | time-sensitive | Blocked — `ImportError: CacheableResult` |
| bench-007 | primary-source | Blocked — `ImportError: CacheableResult` |
| bench-008 | multipart | Blocked — `ImportError: CacheableResult` |
| bench-009 | conflicting | Blocked — `ImportError: CacheableResult` |
| bench-010 | insufficient-evidence | Blocked — `ImportError: CacheableResult` |

Successful cases: 0. Failed cases: 10 (all environmental, none run).

No results were saved to `evaluation/baseline_phase02f/` because no case
produced output. No mock outputs were substituted for real LLM execution.

## 7. Result Preservation (Step 4)

- Original Phase 02A baseline (`evaluation/baseline/`): **preserved untouched**.
- Phase 02F results directory (`evaluation/baseline_phase02f/`): created by the harness but **empty** — no case records were written because every case failed before completion.
- No baseline files were modified or overwritten.

## 8. Baseline Comparison (Step 4)

Not possible — no Phase 02F results exist to compare against the Phase 02A
baseline. The preserved baseline metrics (citation resolution 100% across all
10 cases, claim source coverage 100%, fetch rates 0.0%–9.5% under
`max_sources=3`/`max_fetch_per_query=2`) remain the only available
measurement.

## 9. Regression Verification (Step 5)

All executed and passing after the harness edit:

| Suite | Result |
|---|---|
| Full backend pytest (`tests/unit tests/integration`) | **All pass** — 277 collected test nodes, 0 failures |
| Ruff lint (`ruff check src tests`) | **All checks passed** |
| Ruff format check (`ruff format --check src tests`) | **103 files formatted** |
| MyPy (`mypy src/coraxis`) | **No issues found** (79 source files) |

No tests were removed, weakened, or had expectations changed. The harness
edit (API-key fallback) is covered by existing tests and introduces no
regressions.

## 10. Files Changed (Phase 02F live-benchmark work)

| File | Change | Reason |
|---|---|---|
| `src/coraxis/evaluation/harness.py` | `_eval_llm_config` falls back to `ProviderEnvKeys.key_for(provider)` when `CORAXIS_EVAL_LLM_API_KEY` absent | Harness was not reading the `GROQ_API_KEY` already configured in `.env` |
| `PHASE_02F_LIVE_BENCHMARK_REPORT.md` | New — this report | Documentation |

No other files modified. No dependency versions changed (the mcp/CrewAI conflict was deliberately **not** "fixed" by altering versions, as that is a core dependency change outside Phase 02F scope).

## 11. Limitations and Unverified Areas

| Area | Status | Reason |
|---|---|---|
| Live LLM benchmark execution | **Blocked** | CrewAI/mcp dependency conflict (`CacheableResult` missing from mcp 1.30.0) |
| All 10 case results | **Not produced** | Pipeline fails before any agent runs |
| Quality metrics (citation coverage, unsupported claims, etc.) | **Not measured** | No pipeline output |
| Baseline comparison | **Not possible** | No Phase 02F results |
| Failure analysis per case | **Not possible** | All failures are the same environmental import error |
| Operational performance (latency, tokens, cost) | **Not measured** | No runs completed |
| Human rubric scoring | **Not done** | Requires LLM-produced reports |

To unblock: resolve the CrewAI/mcp dependency conflict (e.g., upgrade CrewAI
to a version compatible with mcp 2.x, or align mcp with a version exposing
`CacheableResult`), then re-run `phase02f_benchmark.py` (saved in temp, not
committed) which saves to `evaluation/baseline_phase02f/`.

## 12. Overall Assessment

- **Was the pipeline successfully benchmarked?** No — blocked by a CrewAI/mcp
  dependency incompatibility before any agent executed.
- **Was the original baseline preserved?** Yes.
- **Were measurable improvements observed?** No — cannot be determined without
  live results.
- **Were any regressions introduced?** No — regression suite fully green
  (277 tests, ruff, mypy).
- **Were credentials exposed?** No — no API key material was printed or logged.
- **Is the evaluation reproducible?** Yes — once the environment dependency
  conflict is resolved, the harness and deterministic tests are ready.

Coraxis should **not** be described as production-ready based on these tests;
they confirm structural/deterministic correctness only, not end-to-end research
quality with a live model.

## 13. Final Git State

- Branch: `main`
- HEAD: `0e008a244b7f85645da0a5a78704e0cc2b173842` (in sync with `origin/main`)
- Working tree: uncommitted (Phase 02A–02F + this report). **Nothing committed,
  nothing pushed.**
- Modified files (this work): `src/coraxis/evaluation/harness.py`,
  `PHASE_02F_LIVE_BENCHMARK_REPORT.md`
- All Phase 02A–02E changes and the migration hardening remain intact and
  uncommitted.

**No commit or push was performed.** Awaiting explicit direction on resolving
the environment dependency conflict before any further benchmark work.
