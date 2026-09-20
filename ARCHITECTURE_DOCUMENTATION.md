# Coraxis — Architecture

This document explains how Coraxis 2.0 is put together and, more usefully, *why*
each significant decision was made. Where a decision reverses something the
previous version did, that is stated explicitly, because the reasoning is the
part that is expensive to reconstruct later.

The audit that identified the problems being solved here is in
[`AUDIT.md`](./AUDIT.md).

---

## 1. Shape of the system

```
                    ┌──────────────────────────────┐
   Browser ────────▶│  Next.js (App Router)        │
                    │  typed client + SSE reader   │
                    └───────────────┬──────────────┘
                                    │  /api/v1 (proxied, same-origin)
                    ┌───────────────▼──────────────┐
                    │  FastAPI                     │
                    │  middleware → routers        │
                    └───────────────┬──────────────┘
                                    │
                    ┌───────────────▼──────────────┐
                    │  services/                   │
                    │  orchestration · auth · runs │
                    └───────┬───────────────┬──────┘
                            │               │
              ┌─────────────▼─────┐   ┌─────▼──────────────┐
              │  repositories/    │   │  agents/           │
              │  the only DB path │   │  framework-free    │
              └─────────┬─────────┘   │  prompts + schemas │
                        │             └─────┬──────────────┘
              ┌─────────▼─────────┐         │
              │  SQLAlchemy 2.0   │   ┌─────▼──────────────┐
              │  SQLite/Postgres  │   │  CrewAI + LiteLLM  │
              └───────────────────┘   └────────────────────┘
```

The dependency rule is one-way: `api → services → repositories → db`.
`agents/` is a sibling of `services/` and imports neither the web framework nor
the database. `workers/` sits alongside `services/` and owns task scheduling.

### Why this matters more than it sounds

In the previous version, `api.py` could not start unless three fake modules were
injected into `sys.modules` — including a mock `streamlit` — because the web
layer imported the pipeline, which imported the UI layer. Roughly 180 of its 731
lines existed to fake a dependency it should never have had.

The fix is not a clever abstraction; it is refusing to let `agents/` know that a
web request exists. The payoff is that the entire pipeline is testable without an
HTTP client, and `import streamlit` now appears nowhere in the codebase.

---

## 2. Configuration

`core/config.py` defines one `Settings` model (pydantic-settings, prefix
`CORAXIS_`), cached with `lru_cache` so it is parsed once.

Two decisions are worth noting.

**CORS origins are a comma-separated string, not a list.** Pydantic-settings
attempts to JSON-decode list-typed fields from the environment, which fails with
a confusing parse error on `a,b`. A `str` field plus a `cors_origin_list`
property removes a class of startup failure.

**A model validator refuses to boot an insecure production instance.** Weak
secrets, a wildcard CORS origin, open registration, and `debug=true` are all
rejected when `CORAXIS_ENV=production`. An app that starts up insecure and looks
healthy is worse than one that refuses to start.

---

## 3. Data layer

### 3.1 Models

Thirteen tables in `db/models.py`. The ones that carry the design:

- **`User`** — `token_version` is a bulk-revocation lever. Bumping it invalidates
  every access token that user holds, immediately, without touching the token
  table.
- **`RefreshToken`** — one row per session, with the JWT's `jti` persisted so a
  token can be revoked. Rotation is tracked by `revoked_at`.
- **`ProviderCredential`** — stores `encrypted_key` and `key_hint`. There is no
  column that holds a usable plaintext key.
- **`AgentDefinition`** — `user_id IS NULL` means "built-in, shared by everyone".
  A nullable owner is a simpler way to express that than a separate table plus a
  union query at read time.
- **`Run`** — a durable record, not in-memory state. `cancel_requested` is the
  cooperative-cancellation flag; `event_seq` tracks the event cursor.
- **`RunEvent`** — one row per event, with `seq` unique per run. This table is
  what makes resumable streaming possible.

### 3.2 Sessions and transactions

`db/session.py` owns engine construction and the two ways to get a session:

- `session_scope()` — used by workers, the CLI and tests. Commits on clean exit,
  rolls back on exception.
- `get_db()` — the FastAPI dependency. **The route decides when to commit.**

Committing in the dependency's teardown would be wrong, and the reason is worth
recording: dependency teardown runs *after* the response has been sent, so a
constraint violation raised there would reach the client as a successful response
whose data was never written. Keeping the commit in the route avoids that, at the
cost of making "forgot to commit" a silent data-loss bug — which is exactly what
happened during this rebuild, in the auth routes. The teardown now logs loudly
when a request finishes with uncommitted changes, so the mistake surfaces
immediately instead of as mysteriously missing rows.

### 3.3 Repositories

`repositories/` is the only code that issues queries. Each function takes a
session and returns models or primitives; none of them commit.

Three implementation details matter:

- **`next_event_seq`** uses `UPDATE … RETURNING` to allocate sequence numbers
  atomically. Two concurrent writers cannot collide.
- **`mark_finished`** returns early if the run is already terminal, so a late
  timeout cannot overwrite a successful result.
- **`is_cancel_requested`** re-queries rather than reading a cached attribute.
  The worker may hold a stale ORM instance while the user clicks Cancel in a
  different request.

### 3.4 Migrations

Alembic, configured with an async `env.py` that reads the URL from settings
rather than `alembic.ini`. `render_as_batch` is enabled on SQLite, which cannot
`ALTER COLUMN` and needs table rebuilds.

The app refuses to start if the schema is behind the migration head. Booting
against an unmigrated database produces confusing runtime errors; failing fast
with "run `coraxis init`" does not.

---

## 4. Authentication

### 4.1 Tokens

Argon2id for passwords. HS256 JWTs with a short access lifetime and a long
refresh lifetime.

`TokenClaims` carries `sub`, `type`, `jti`, `ver` and `sid`:

- **`type`** distinguishes access from refresh. Without it, a refresh token would
  be accepted as an access token — a classic privilege bug. `decode_token` takes
  the expected type and rejects anything else.
- **`ver`** is compared against `User.token_version` on every request. Because
  the dependency re-reads the user, a bumped version takes effect on the next
  request rather than at token expiry.
- **`sid`** is the `jti` of the refresh token issued alongside the access token.
  It exists so a request can identify *which* session it is using. Access and
  refresh tokens have distinct `jti` values by construction, so comparing them
  directly can never match — which is precisely the bug that made the
  "this device" marker on the sessions screen always false.

### 4.2 Refresh rotation and reuse detection

Refresh tokens are single-use. Presenting one that has already been rotated is
treated as theft: every session for that user is revoked and the request is
rejected.

The revocation is committed *inside* `refresh_tokens`, before the exception is
raised. This is deliberate and load-bearing. The request-scoped session rolls
back when an exception propagates, so without that commit the theft response
would silently undo itself and leave the attacker's rotated token working — a
security control that fails open and reports success.

### 4.3 Credential encryption

`core/crypto.py` derives a Fernet key from `CORAXIS_SECRET_KEY` via HKDF-SHA256
with a fixed salt and info string. `CORAXIS_ENCRYPTION_KEY` can override the
derivation, which decouples encryption from signing — so rotating the JWT signing
key does not orphan every stored credential.

A decrypt failure raises a `ConfigurationError` that names the cause and the fix
("re-enter the key"), rather than surfacing as an opaque 500.

### 4.4 Why a key never comes back

`CredentialOut` has no field capable of carrying a key. The endpoint does not
decide to withhold it; the response schema cannot express it. `key_hint` is the
last four characters, enough to tell two keys apart and useless otherwise.

This is a response to the audit's finding C2, where `GET /api/agents` spread the
credential row into its response with `**ac` and returned plaintext keys, while
`GET /api/config` masked them correctly. Making disclosure unrepresentable is
more durable than remembering not to do it.

---

## 5. Errors

One exception hierarchy rooted at `CoraxisError`, each subclass carrying a
`status_code`, a stable machine-readable `code`, and a human `detail`.
`register_exception_handlers` maps them to RFC 7807 `application/problem+json`
documents, and also handles `RequestValidationError`, `StarletteHTTPException`
and bare `Exception`.

Two consequences worth stating:

- **Every response looks the same.** The client has exactly one error shape to
  parse, and a `request_id` that correlates with the server log line for that
  request.
- **`problem_response` is public.** Errors raised in middleware never reach an
  exception handler — the route was never entered — so middleware needs to build
  the same envelope itself.

---

## 6. The research pipeline

### 6.1 Domain layer

`agents/` contains prompts, Pydantic output schemas, the citation tracker, the
tool implementations and crew construction. It imports CrewAI and nothing from
Coraxis except `core/errors`.

`agents/citations.py` assigns each source a reference number **once**, at first
sight, and never recomputes it. The previous implementation derived the number
from the citation's position in an ordered dict, so adding a source could
silently renumber references already written into a saved report. There is a
regression test for this.

`add_claim` deliberately does not influence a source's relevance unless an
explicit score is supplied. An earlier version fell back to a default of `0.7`,
which meant a page the search tool had scored `0.0` would jump to `0.7` the
moment any claim cited it — inflating the relevance statistics the report is
built on.

### 6.2 Blocking libraries

DuckDuckGo search, Trafilatura extraction and ChromaDB are synchronous. Every
call to them goes through `asyncio.to_thread`, so they cannot stall the event
loop.

The previous version called `asyncio.run()` from inside library code, which
raises if a loop is already running. `tools/crew_tools.py` now raises a clear
error explaining that CrewAI's synchronous tool entry point cannot be used from
inside a running loop, and points at `kickoff_async()`.

### 6.3 Events

`RunEventBus` is an in-process pub/sub keyed by run id. Publishing from a worker
thread goes through `call_soon_threadsafe`, because putting to an `asyncio.Queue`
from another thread is not safe. Subscribers that fall behind are dropped
oldest-first rather than growing without bound.

`EventRecorder` batches writes — one transaction per batch, flushed on a size or
time threshold — instead of rewriting a JSON file on every event, which is what
the previous version did.

Ordering matters and is enforced: **persist first, then broadcast.** If the write
fails, the event is not broadcast, so a client can never see an event that a
reconnecting client would not find in the database.

### 6.4 Execution

`ResearchOrchestrator.execute` always writes a terminal state, including on
unexpected failure. Runs execute as `asyncio.Task`s behind a semaphore, not as
daemon threads, which is what makes cancellation and bounded concurrency
possible.

On startup, `recover_interrupted_runs` marks any run left in `running` by a
previous process as failed. A crash cannot leave a run stuck forever.

Cancellation is cooperative: the endpoint sets a flag, and the tools and
orchestrator check it between steps. A run stops within a few seconds rather than
instantly, and the API says so.

### 6.5 Quotas

Checked in `services/runs.submit`, not in the route, so every path into
execution — API, retry, scheduled job — is subject to the same limits: an hourly
rate limit, a per-user concurrency cap, and a run timeout.

---

## 7. Streaming

`GET /api/v1/runs/{id}/stream` returns `text/event-stream`.

The protocol:

1. On connect, read the cursor from `Last-Event-ID` or `?since=`.
2. Replay persisted events after that cursor.
3. If the run is already terminal, emit `stream.closed` and end.
4. Otherwise subscribe to the bus and forward live events, skipping any with a
   `seq` at or below the cursor.
5. Emit a comment frame every 15 seconds so intermediaries do not close an idle
   connection.

Because events are persisted before broadcast, the replay is exact and gap-free.
The client reconnects with the last `seq` it saw and receives precisely what it
missed.

`X-Accel-Buffering: no` and `Cache-Control: no-transform` are set so proxies do
not buffer the stream into uselessness.

---

## 8. Rate limiting

`core/ratelimit.py` implements a sliding window, in-process and dependency-free.

It is honest about its limit: with `--workers N`, each worker keeps its own
window, so the effective limit is `N × limit`. Every call site goes through
`enforce`, so swapping in a Redis-backed implementation is a one-file change.

The key map has a hard ceiling. Evicting only *stale* buckets is not sufficient —
a client rotating identities faster than the window expires keeps every bucket
alive, so nothing is ever stale and the map grows without bound. When the ceiling
is reached, the least recently active buckets are evicted too.

---

## 9. Frontend

### 9.1 One client

Every request goes through `lib/api.ts`. Three invariants hold there rather than
at 15 call sites:

- Errors are parsed into `ApiError` carrying the problem document, so a failure
  is never silent.
- The bearer token is attached automatically.
- A 401 triggers exactly one refresh-and-retry.

That last one depends on `lib/session.ts` serialising refresh behind a single
in-flight promise. Refresh tokens are single-use, and the server treats a replay
as theft by revoking every session. If two requests 401 simultaneously and both
refresh, the second presents an already-rotated token and the user is signed out.
Single-flight refresh is what stops the app from logging itself out under normal
concurrent load.

### 9.2 Streaming

The SSE stream is consumed with `fetch` and a `ReadableStream` reader, not
`EventSource`. `EventSource` cannot send an `Authorization` header, and the usual
workaround — a token in the query string — writes the token into every access log
and proxy trace along the way. It also cannot send `Last-Event-ID`, so it cannot
resume from an explicit cursor.

### 9.3 Derived state

The old frontend polled `/api/status` every 1.2 seconds for a pre-computed
`agent_states` map, which put presentation logic in the API. Agent progress is
now derived in `lib/derive.ts` from the event stream, in the layer that renders
it. Nothing is polled on a timer.

### 9.4 Component split

`src/app/page.tsx` was 2,049 lines holding navigation, four feature tabs, a
modal, a landing page and fifteen `fetch` calls. It is now a composition root
that owns navigation, the toast queue and the session gate. Feature views live in
`components/`, data access in `lib/` and `hooks/`.

---

## 10. Testing

Unit tests cover pure logic: crypto round-trips, password and token handling,
citation numbering, rate-limit windows, report parsing.

Integration tests drive the real HTTP stack against a real temporary database.
They cover the auth lifecycle, run lifecycle and quotas, cross-account isolation,
and — most importantly — a sweep of every documented `GET` route asserting that a
stored credential is never returned. That test exists because the audit found one
endpoint leaking keys while another masked them; checking only the endpoint that
was broken would not have caught it.

Several of the bugs fixed during this rebuild were found by these tests rather
than by reading the code: the uncommitted auth writes, the `sid` claim, the
rolled-back theft response, and the terminal-event type mismatch that left failed
runs stuck in `running`. That is the argument for integration coverage over more
unit tests.

---

## 11. Known limits

Stated plainly, because a document that claims none is not useful:

- **The run runner is in-process.** Runs execute as asyncio tasks in one process.
  Scaling out means replacing `workers/runner.py` with a queue-backed
  implementation. Because run state already lives in the database with a status
  column, that swap does not touch the API or the orchestrator.
- **Rate limiting is per-worker.** See §8.
- **Event broadcasting is in-process.** A multi-worker deployment would need a
  shared bus (Redis pub/sub or similar) for the SSE stream to see events
  published by other workers. Replay from the database still works; only the live
  tail would be incomplete.
- **The event bus is best-effort.** A subscriber that falls behind is dropped
  rather than back-pressured, on the assumption that it can reconnect and replay.
- **No cost accounting.** `RunStats` records models used, not token spend.
