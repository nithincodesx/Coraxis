# Coraxis — Repository Audit

**Repository:** `nithincodesx/Coraxis`
**Audited:** 2026-09-16
**Audited revision:** `be7eebf` (main) — "Resolve merge conflicts by keeping local version"
**Scope:** structure, tech stack, functionality, dependencies, defects, and readiness for a ground-up rebuild.

---

## 1. Executive summary

Coraxis is a **solo-built, four-agent autonomous research pipeline** that decomposes a query, searches the web, synthesises cited findings, and returns a markdown report. The agent design is genuinely good — clear role separation, a real citation tracker, and a semantic memory layer. The problem is everything underneath it.

The codebase is a **Streamlit application wearing a FastAPI costume**. The API server can only start by injecting a fake `streamlit` module into `sys.modules` and stubbing out two of its own UI components. On top of that sit three structural blockers: **zero authentication** with stored API keys readable in plaintext over HTTP, a **process-wide singleton** that permits exactly one research run at a time, and **daemon threads** as the entire concurrency and durability story.

Verdict: **not shippable, and not repairable by patching.** The pipeline logic is worth keeping; the application shell needs to be rebuilt.

| Dimension | Rating | Note |
|---|---|---|
| Agent / prompt design | Good | Clear roles, real task schemas, citation-aware tools |
| API design | Poor | Unversioned, untyped errors, no auth, no pagination |
| Data handling | Poor | JSON files, no DB, no migrations, no transactions |
| Authentication | **Absent** | No auth of any kind; keys exposed |
| Error handling | Poor | Broad `except: pass` in critical paths |
| Scalability | **Blocked** | Global singleton + one-run gate + daemon threads |
| Test / CI posture | Poor | 15 tests, no CI, no coverage, targets legacy modules |
| Documentation | Poor | Three different product names for one product |

---

## 2. Repository status (live from GitHub API)

| Field | Value |
|---|---|
| Created | 2026-08-21 |
| Last push | 2026-09-13 |
| Default branch | `main` |
| Branches | `main`, `docs/add-idea-notes` (stale) |
| Commits | 65 |
| Contributors | `nithincodesx` (44), `nithin` (20) |
| Stars / forks / watchers | 2 / 0 / 2 |
| Open issues / PRs | 0 / 0 (one closed PR: #1, docs) |
| Topics | *(none)* |
| License | **null** — README claims MIT, no `LICENSE` file exists |
| CI | **none** — no `.github/` directory |
| Languages | Python 223 KB · TypeScript 100 KB · CSS 45 KB · JavaScript 559 B |

Activity is bursty: an initial build on 2026-08-21/22, a large feature push on 2026-08-27, a burst of fixes on 2026-08-23, then a single "Update" + conflict-resolution commit on 2026-09-13. Since then, nothing. The `docs/add-idea-notes` branch is merged and stale.

### Working-tree notes
`data/config.json` does not exist locally, so the running app silently falls back to built-in defaults. `chroma_db/` exists but is empty of tracked content. Two large `.png`/`.log` artifacts (`dribbble-shot.png` 732 KB, `streamlit.log` 15 KB, `frontend_boot.log` 29 KB) are tracked or present in the working tree and should not be.

---

## 3. Tech stack as-built

**Backend**
- FastAPI 0.141 + Uvicorn — REST API on `127.0.0.1:8000`
- CrewAI 1.15.17 + LangChain 1.3 / `langchain-core` 1.6 — agent orchestration
- LiteLLM 1.98 — provider abstraction and fallback
- ChromaDB 1.1.1 + `sentence-transformers` (`all-MiniLM-L6-v2`) — semantic memory
- `duckduckgo-search` 8.1.1 — web search
- Trafilatura + readability-lxml — content extraction
- Pydantic 2.12 + pydantic-settings — models (settings module is unused)
- Stdlib `threading` — background execution

**Frontend**
- Next.js 16.3.1 (App Router, Turbopack), React 19.2.8, TypeScript 5
- Tailwind CSS 4, `lucide-react` 1.33
- No state library, no data-fetching library, no API client, no test runner

**Legacy (still present, no longer reachable)**
- Streamlit 1.38+, Altair 6, Plotly 6, Pandas 3, WeasyPrint, scikit-learn, python-slugify, markdown

**External services**
- Groq (default), Google Gemini, OpenAI, Ollama (local)
- MCP config for an "AAS Core" skill catalog and `agent-browser`

---

## 4. What actually works

Verified by reading the code and the runtime logs (`backend_boot.log`, `frontend_boot.log`).

Working:
- `GET /api/health`, `/api/metrics`, `/api/config`, `/api/history`, `/api/status`, `/api/logs`, `/api/agents`, `/api/teams` all return 200 against a running server (confirmed in `backend_boot.log`).
- The 4-agent sequential CrewAI pipeline is coherent: `agents.py` → `tasks.py` → `crew.kickoff()` with Pydantic `output_json` schemas per task.
- `CitationTracker` (`tools/citations.py`) correctly tracks sources, claims, confidence, relevance, and emits `[^n]` markdown references.
- Provider key resolution precedence (global → per-agent → env) is implemented and unit-tested.
- The LiteLLM `cache_breakpoint` sanitiser and Groq model-fallback shim are real, hard-won compatibility fixes.
- The Next.js frontend builds and renders; `next.config.ts` rewrites `/api/*` to the backend.

Not working / broken:
- **The backend cannot be imported normally.** It only boots because `api.py` fabricates a `streamlit` module before importing its own pipeline. Any standard tool that imports the package — pytest collection, mypy, an IDE, `uvicorn` with a preloaded app, a test harness — fails.
- **No run survives a restart.** History lives in `mock_st.session_state["research_history"]`, a plain in-memory dict.
- **Concurrency is impossible.** One global `state` object and a single `is_running` boolean gate every endpoint.
- **Multi-worker deployment is impossible.** `uvicorn --workers N` would create N conflicting copies of `state`, `config_store._cache`, and the ChromaDB singleton.
- **Exported reports are branded with the wrong product name** (`utils/export.py` writes `"Kimi Multi-Agent Research Assistant"` into YAML frontmatter).

---

## 5. Findings

Severity: **C** critical · **H** high · **M** medium · **L** low.
Evidence cites `file:line` at revision `be7eebf`.

### Critical

**C1 — No authentication; API keys readable over HTTP.**
`api.py:223-229` installs CORS with `allow_origins=["*"]` **and** `allow_credentials=True`. Not a single route has an auth dependency. Anyone or anything that can reach port 8000 can enumerate configured agents, read stored provider credentials, overwrite them, and start runs that spend the owner's quota. Separately, `*`-origin plus credentials is rejected by browsers per the CORS spec — so the configuration is simultaneously insecure and non-functional for credentialed requests.

**C2 — Provider API keys are returned in plaintext and stored unencrypted.**
`GET /api/agents` (`api.py:596`) spreads the raw config: `{"name": name, "builtin": True, **ac, "api_key_set": ...}` — that `**ac` includes `api_key`. Compare `GET /api/config` (`api.py:328`), which correctly masks it as `key_set`. The two endpoints disagree about whether secrets are secret. On disk, `utils/config_store.py:96-102` writes them verbatim into `data/config.json` with no encryption, no file permissions hardening, and no secret redaction in logs.

**C3 — Global mutable singleton; one run for the entire server.**
`api.py:85-103` defines `GlobalState` and instantiates it at module scope as `state`. Every run overwrites `state.run_query`, `state.final_report`, `state.citation_tracker`, `state.activity_feed`. `api.py:577-578` and `api.py:641-642` reject any second request with `400 "Research is already in progress."` This is a hard ceiling of one concurrent user, and it makes multi-worker deployment not merely inefficient but incorrect.

**C4 — The backend only runs by faking Streamlit.**
`api.py:24-81` builds a ~60-attribute mock `streamlit` module and injects it via `sys.modules["streamlit"] = mock_st` (`api.py:81`). `api.py:110-206` then fabricates `components.timeline` and `components.activity_feed` and injects those too. This is required because `utils/streaming.py:7` does `import streamlit` for real, and the mocked components call into the pipeline. Roughly **180 lines of the 731-line API file exist solely to work around the framework the project abandoned.** It is the single largest source of fragility in the repo.

### High

**H1 — Daemon threads as the execution and durability model.**
`api.py:581-583` and `api.py:677-678` run the pipeline via `threading.Thread(..., daemon=True).start()`. Consequences: no job store, no cancellation, no retry, no concurrency limit, no persistence, and silent termination of in-flight work on shutdown. There is no way to ask "what runs are active?" or "re-run run #7".

**H2 — SSE queue is written from a worker thread.**
`api.py:697-721` creates an `asyncio.Queue` and registers `_on_event`, which calls `queue.put_nowait(...)` — but `_on_event` fires on the **CrewAI worker thread**, not the event loop. `asyncio.Queue` is not thread-safe, so events can be lost, misordered, or raise. Additionally, if a client disconnects without the generator being closed, `comms.unsubscribe` may never run and the subscriber list grows without bound.

**H3 — `asyncio.run()` inside synchronous methods.**
`tools/search.py:70` and `tools/search.py:109` call `asyncio.run(self.arun(...))`. Any caller already inside an event loop gets `RuntimeError: asyncio.run() cannot be called from a running event loop`; every call also spins up and tears down a fresh event loop. This works today only because the pipeline happens to run on a bare thread.

**H4 — Blocking I/O on the event loop, and a leaked HTTP client.**
`tools/search.py:157` calls Trafilatura's **synchronous** `fetch_url` from inside `async def arun`, stalling the loop for the full network round-trip. `PageFetchTool.__init__` (`tools/search.py:128-137`) constructs an `httpx.AsyncClient` that is only closed through `async with`, yet `run()`/`arun()` are routinely called directly — so each instantiation leaks a connection pool.

**H5 — Failures are swallowed in critical paths.**
`api.py:474-475`: `_save_to_memory_api` wraps its whole body in `try/except Exception: pass`. `utils/comms.py:118-121`: subscriber callback exceptions are discarded. `utils/comms.py:61-62` and `:67-68`: persistence failures are silently ignored. Memory writes and event persistence can fail permanently with no signal anywhere.

**H6 — Config writes are not safe across processes.**
`utils/config_store.py:46-102` guards state with a process-local `threading.RLock` and a module-level `_cache`. `set_agent_config` (`:150-176`) is a read-modify-write over that cache. A second process, a reloader, or a worker will silently clobber the first. There are no transactions and no schema versioning.

**H7 — No database; full-file rewrites on every event.**
State lives in `data/config.json`, `data/events.json`, and `data/blackboard.json`. `utils/comms.py:55-68` serialises **the entire event ring buffer and the entire blackboard** to disk on *every single* `publish()` call, via `_persist()` invoked from `publish` (`utils/comms.py:115`) and again from `bb_write` (`:165`). A busy run performs thousands of full-file writes. The blackboard trim path (`:161-164`) sorts all entries on every write over the limit.

**H8 — No rate limiting, no timeout, no cost guard.**
The only throttle anywhere is CrewAI's `max_rpm=10` (`tasks.py:231`, `teams.py:203`), which is per-Crew, not per-user or per-key. There is no request timeout, no max-runtime, no token budget, and no per-user quota. A runaway agent loop burns a free-tier quota with nothing to stop it.

### Medium

**M1 — Three product names for one product.**
`README.md` says **Coraxis**. `ARCHITECTURE_DOCUMENTATION.md` says **Synapse**. `api.py:2`, `api.py:221`, `.streamlit/config.toml`, and `utils/export.py:25` say **Kimi**. `pyproject.toml:2` declares `name = "kimi-research-assistant"`. The practical consequence: every exported report is stamped with the name of a product that no longer exists.

**M2 — README claims MIT; no license exists.** GitHub reports `"license": null` and there is no `LICENSE` file. Without one the work is legally all-rights-reserved, which contradicts the "clone and run it" pitch.

**M3 — `pyproject.toml` declares `dependencies = []`.** The package would install nothing while claiming to be the project's build definition.

**M4 — No CI, minimal tests.** No `.github/`. Two test files, 15 test functions (`tests/test_llm_factory.py`, `tests/test_config_comms_teams.py`), no coverage configuration, no `pytest` in `requirements.txt` (it is commented out). The tests that exist target the LLM factory and legacy config/comms modules — nothing covers the API, the pipeline, or the frontend.

**M5 — Large dead-code surface.** `app.py` (572 lines) and all eight `components/*` modules (~1,030 lines) plus `styles/custom.css` are Streamlit-only and unreachable from the shipping Next.js product. `utils/export.py` (309 lines) depends on WeasyPrint, which needs GTK system libraries on Windows — a documented install trap that serves only the legacy PDF path.

**M6 — Dependencies are unpinned and mixed.** `requirements.txt` uses `>=` throughout with no lockfile, so builds are not reproducible. It also conflates the shipping backend (`fastapi`, `crewai`, `chromadb`) with legacy UI packages (`streamlit`, `weasyprint`, `altair`, `plotly`, `pandas`, `scikit-learn`), so anyone installing to run the web app pulls the entire abandoned stack.

**M7 — The frontend is a 2,049-line single file.** `frontend/src/app/page.tsx` holds all state, 15 hand-rolled `fetch` calls, SSE handling, and every view. There are no shared types, no API client, no error envelope, no retry, and no `AbortController` — so a user navigating away mid-run leaves requests in flight. Zero frontend tests and no test runner configured.

**M8 — Two redundant realtime channels.** The client subscribes to SSE at `/api/comms/stream` *and* polls `/api/status` and `/api/logs` on an interval. `backend_boot.log` shows a continuous flood of `GET /api/status 200`. Neither channel supports cursors, ETags, or `Last-Event-ID`, so every poll re-sends the full payload.

**M9 — MCP config is broken for every clone.** `mcp_config.json` points at `./.agents/skills/agentic-awesome-skills/mcp-server.js`, but `.agents/` is listed in `.gitignore`. A fresh clone gets a config referencing a file that does not exist.

**M10 — Merge hygiene risk, already realised once.** Commit `be7eebf` is titled "Resolve merge conflicts by keeping local version", and `frontend_boot.log` records the fallout: `Error: Merge conflict marker encountered.` with `>>>>>>>` at `page.tsx:43`, breaking the build. The markers are resolved in the current working tree (verified: zero remaining), but the resolution style — discarding one side wholesale — is how the frontend and its API contract drifted. The same repo also carries two author identities (`nithincodesx`, `nithin`) across 64 commits, splitting contribution history.

**M11 — O(n²) citation numbering that can drift.** `tools/citations.py:149` computes a citation's reference number with `list(self.citations.keys()).index(cit_id) + 1` inside a loop. It is quadratic, and because the number is positional rather than stable, the `[^n]` markers already written into a saved report can stop matching the tracker if citations are ever added or reordered.

**M12 — Dead imports and stale exports.** `agents.py:10` and `tasks.py:11` both import `get_available_providers` without using it. `tools/__init__.py` re-exports names that no longer resolve to the current module layout. `README.md` documents `tools/search_tools.py`, which does not exist (the file is `tools/search.py`).

### Low

**L1 — `start.py` orchestration is race-prone.** `start.py:38` sleeps a fixed 2 seconds instead of polling readiness, and `start.py:42-43` launches the frontend with `shell=True`. `start.py:50` blocks on the backend first, so if the backend dies the frontend is orphaned.

**L2 — Dev-only server setting in the shipped entrypoint.** `api.py:731` runs `uvicorn.run(..., reload=True)`.

**L3 — No observability.** No request IDs, no structured logging, no trace correlation, no Prometheus endpoint. `GET /api/metrics` returns a hand-rolled JSON blob, not metrics.

**L4 — Unbounded local data growth.** `data/events.json` and `data/blackboard.json` grow without rotation; trimming is capped but performed by full re-sort on every write.

**L5 — Tooling configured but never run.** `pyproject.toml` configures Ruff and mypy with a Python 3.11 target; neither runs in CI, and there is no `py.typed`.

---

## 6. Rebuild plan

The pipeline is the asset. Everything around it is the liability. The rebuild therefore **keeps the agent/task/citation/memory logic as domain code** and replaces the application shell.

### Target shape

```
src/coraxis/
  main.py            app factory + lifespan
  core/              settings, security, crypto, logging, errors, rate limiting
  db/                async engine, SQLAlchemy 2.0 models, Alembic migrations
  schemas/           request/response DTOs
  repositories/      data access
  services/          llm registry · research orchestration · citations · memory
  agents/            crew, tasks, tools  (domain logic preserved)
  api/v1/            versioned routers
  workers/           durable job runner
tests/               unit · integration · e2e
```

### Fix mapping

| Finding | Resolution |
|---|---|
| C1, C2 | Auth dependency on every route; JWT bearer; provider keys encrypted at rest; explicit CORS allowlist; secrets never serialised outbound |
| C3, H1, H2 | Durable run records in the DB; a real job runner; per-run SSE with `Last-Event-ID`; no module-level mutable state |
| C4 | Delete the Streamlit mock entirely; extract the pipeline into a framework-free service; no UI framework imported by the backend |
| H3, H4 | Single async I/O path; no `asyncio.run` in library code; one shared, lifecycle-managed HTTP client |
| H5 | Typed exception hierarchy, RFC 7807 responses, no bare `except: pass` |
| H6, H7 | SQLite (Postgres-compatible) with SQLAlchemy 2.0 async + Alembic; transactional writes; event persistence batched, not per-event |
| H8 | Per-user rate limits, run timeouts, token budgets |
| M1–M3 | One name; `LICENSE` file; real project metadata |
| M4 | CI workflow running lint, type check, and tests with coverage |
| M5, M6 | Legacy Streamlit stack removed; pinned, layered dependencies |
| M7, M8 | Typed API client + hooks; single realtime channel with cursors |
| M9–M12 | MCP config made portable; stable citation IDs; dead code removed |

### Explicitly out of scope for v1
Authentication beyond single-tenant JWT, billing, horizontal scale-out, and multi-region. The design leaves room for each without committing to them.

---

## Resolution status

**Verified 2026-09-17** against the rebuilt tree, by running it — not by reading it.

Every claim below was checked by one of: the test suite (104 tests), a live
end-to-end session against a fresh database, `ruff`, `mypy`, `tsc`, `eslint`, or
`next build`.

| Finding | Status | Evidence |
|---|---|---|
| C1 No authentication | **Resolved** | Argon2id, JWT with `type`/`ver`/`sid` claims, rotating refresh tokens. Integration tests cover register, login, rotation, reuse detection, logout, and that a refresh token is rejected as an access token. |
| C2 Keys returned in plaintext | **Resolved** | Fernet-encrypted at rest; `CredentialOut` has no field that can carry a key. A test sweeps **every documented `GET` route** and asserts a sentinel key appears in none. |
| C3 Global singleton | **Resolved** | Runs are per-user rows; `RunRunner` is an asyncio semaphore. Two accounts can run concurrently, and one cannot read the other's run (tested). |
| C4 Runs only by faking Streamlit | **Resolved** | `import streamlit` appears nowhere. `coraxis serve` boots and serves with no mocks. |
| H1 Daemon threads | **Resolved** | `asyncio.Task`s with cooperative cancellation; `recover_interrupted_runs` reaps orphans on boot (observed: `marked 1 interrupted run(s) as failed`). |
| H2 SSE queue written cross-thread | **Resolved** | `call_soon_threadsafe`. |
| H3 `asyncio.run()` in library code | **Resolved** | Guarded with an error naming the fix and pointing at `kickoff_async()`. |
| H4 Blocking I/O on the loop | **Resolved** | DuckDuckGo, Trafilatura and ChromaDB all go through `asyncio.to_thread`; one lifecycle-managed client. |
| H5 Swallowed failures | **Resolved** | Typed hierarchy → RFC 7807. The one remaining broad catch (`_finalise`) logs with a traceback and is covered by tests asserting the terminal state is still written. |
| H6 Cross-process config writes | **Resolved** | Per-user rows with transactions; no shared JSON file. |
| H7 No database, full-file rewrites | **Resolved** | SQLAlchemy 2.0 async + Alembic; one row per event, written in batches. |
| H8 No limits | **Partly resolved** | Rate limiting, per-user concurrency cap, and run timeout are in and tested. **Token/cost accounting is not implemented** — see "Known limits" in the architecture doc. |
| M1 Three product names | **Resolved** | One name throughout. |
| M2 No licence | **Resolved** | `LICENSE` present. |
| M3 Empty `dependencies` | **Resolved** | Real dependency list with `dev`/`postgres` extras; `requirements.txt` regenerated and separated from the legacy stack. |
| M4 No CI, 15 tests | **Resolved** | CI runs lint, format, mypy and tests on 3.11 + 3.12, plus a Postgres job. **104 tests**, including integration coverage of auth, runs, quotas and isolation. |
| M5 Dead-code surface | **Resolved** | Streamlit app and components moved to `legacy/`. |
| M6 Unpinned mixed dependencies | **Resolved** | Bounded ranges in `pyproject.toml`; legacy stack no longer pulled. |
| M7 2,049-line frontend file | **Resolved** | Composition root plus `components/`, `hooks/` and a typed client. `tsc` and `eslint --max-warnings 0` clean; `next build` succeeds. |
| M8 Two realtime channels | **Resolved** | One SSE stream with `Last-Event-ID` resume. Nothing polls on a timer. |
| M9 Broken MCP config | **Open** | Still references the gitignored `./.agents/` path. Left in place deliberately — it is the maintainer's local agent tooling, not a product file, and moving it could break a workflow this rebuild cannot see. **Needs a decision.** |
| M10 Merge hygiene | **Resolved** | No conflict markers; single-product docs; the frontend contract now comes from the server's own OpenAPI schema. |
| M11 O(n²) citation numbering | **Resolved** | Numbers assigned once at first sight; regression test covers it. |
| M12 Dead imports | **Resolved** | Ruff enforces it; README references corrected. |
| L1 Race-prone `start.py` | **Resolved** | `coraxis dev` polls readiness instead of sleeping. |
| L2 `reload=True` in shipped entrypoint | **Resolved** | `serve` defaults to no reload. |
| L3 No observability | **Resolved** | Request IDs, structured logging, `/metrics`, `/ready`. |
| L4 Unbounded local growth | **Resolved** | Relational storage with a bounded SSE replay window. |
| L5 Tooling never run | **Resolved** | All gates run in CI and pass locally; `py.typed` added. |

### Bugs found during the rebuild that the audit did not predict

The audit described the old system. Rebuilding it surfaced a further set of
defects, all now fixed and each covered by a test:

1. **Auth routes never committed.** Registration, login, refresh and logout were
   silently rolled back. Found by an integration test asserting persistence.
2. **Session `is_current` was always false.** Compared an access token's `jti`
   with refresh-token `jti`s, which never match. Fixed with a `sid` claim.
3. **Refresh-token reuse detection was rolled back.** The revocation was undone
   by the error path, so the theft response failed open. Now committed before the
   raise.
4. **Failed runs hung in `running` forever.** A `str` was passed where an enum
   was expected in the final write of a failed run. Found only by running a real
   pipeline against a real provider.
5. **Claim registration inflated source relevance**, letting a `0.0`-scored page
   jump to `0.7` as soon as a claim cited it.
6. **The rate-limiter key map had no hard ceiling**, so rotating identities grew
   it without bound.
7. **`serve --port` logged the wrong port**, sending anyone reading the log to
   the wrong address.

The pattern is worth noting: none of the first four were visible to unit tests.
They needed a real database, a real transaction boundary, and a real failing run.

