# Coraxis — Autonomous Multi-Agent Research Platform

> Four specialised agents research a topic end to end: decompose the question, search the web, fetch and cross-check sources, score claims, and hand back a cited report. Watch it happen live over resumable SSE. Runs on a free stack — Groq, Gemini, OpenAI, or a local Ollama model — with Firebase Auth, encrypted provider keys at rest, per-user quotas, and a SQL persistence layer.

Coraxis 2.0 is a ground-up rebuild of a Streamlit app that had grown a FastAPI shim, a global singleton that allowed exactly one run per server, no authentication, and an endpoint that returned stored API keys in plaintext. The audit that drove this rewrite is in [`AUDIT.md`](./AUDIT.md); the design decisions are in [`ARCHITECTURE_DOCUMENTATION.md`](./ARCHITECTURE_DOCUMENTATION.md).

---

## What it does

| Feature | Detail |
|---|---|
| **Four-agent pipeline** | Researcher → Web Searcher → Synthesis Analyst → Report Writer. Each agent has its own prompt, task schema, tools, and model. Built on CrewAI + LiteLLM; the pipeline itself is framework-free domain code that imports neither FastAPI nor SQLAlchemy. |
| **Live, resumable progress** | Every event is persisted to a per-run `run_event` table with a monotonic sequence number before it is broadcast over SSE. A dropped connection replays exactly what was missed (`Last-Event-ID`) instead of starting over. |
| **Citations that don't drift** | Reference numbers are assigned once, at first sight, and never recomputed. A saved report keeps the same `[^n]` numbering it had when it was written. |
| **Multi-user by default** | Accounts with Argon2id password hashing, short-lived JWT access tokens with rotating refresh tokens, per-session revocation, and logout. |
| **Firebase Auth** | GitHub OAuth and email/password identity handled by Firebase; the backend verifies the Firebase ID token sent as the bearer token on every protected route. |
| **Credentials encrypted at rest** | Provider keys are Fernet-encrypted with a key derived from `CORAXIS_SECRET_KEY` (or an independent `CORAXIS_ENCRYPTION_KEY`). The API returns only a key hint; no response schema has a field capable of carrying a key. |
| **Custom agents & teams** | Define your own agents, compose them into teams, and run either the default pipeline or a saved team. Per-agent LLM settings (provider nickname, model, base URL) with encrypted key storage. |
| **Semantic memory** | Findings are embedded into a per-user ChromaDB collection so later runs can recall earlier work, with a relational mirror so the index can be rebuilt. |
| **Quotas & limits** | Per-user rate limits (runs/hour, requests/minute), run timeouts, and a concurrency cap so one runaway agent loop cannot burn a free-tier quota. |
| **SQL backend** | SQLAlchemy 2.0 async + Alembic migrations. SQLite by default; PostgreSQL works unchanged via `postgresql+asyncpg://…`. One row per run, per event — no global mutable state, no daemon threads. |

---

## Architecture

```
Browser ─────────▶ Next.js (App Router)
                    typed client + SSE reader
                                    │  /api/v1 (proxied, same-origin)
                                    ▼
                              FastAPI
                              middleware → routers
                                    │
                    ┌───────────────┴───────────────┐
                    │  services/                    │
                    │  orchestration · auth · runs  │
                    └───────┬───────────┬───────────┘
                            │           │
              ┌─────────────▼─┐   ┌─────▼─────────────┐
              │ repositories/ │   │ agents/           │
              │ only DB path  │   │ framework-free    │
              └───────────────┘   │ prompts + schemas │
                                  └─────┬─────────────┘
                                        │
                            ┌───────────▼───────────┐
                            │ CrewAI + LiteLLM      │
                            └───────────────────────┘
```

Imports point one way only: `api → services → repositories → db`, with `agents/` sitting beside `services/` as a pure domain layer that imports neither the web framework nor the database. That is what lets the pipeline be unit-tested without an HTTP client.

The frontend is a Next.js App Router app whose data layer is a single typed client (`frontend/src/lib/api.ts`) over `/api/v1` (proxied same-origin). It holds no business logic.

### Why this shape

In the previous version, the API could not start unless three fake modules were injected into `sys.modules` — including a mock `streamlit` — because the web layer imported the pipeline, which imported the UI layer. Roughly 180 lines existed solely to fake a dependency it should never have had. The fix: refuse to let `agents/` know a web request exists. `import streamlit` now appears nowhere in the codebase.

---

## Quick start

Requires **Python 3.11+** and **Node 18+**.

### Backend

```bash
git clone https://github.com/nithincodesx/Coraxis.git
cd Coraxis

python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate

pip install --upgrade pip
pip install -e ".[dev]"

cp .env.example .env
# CORAXIS_SECRET_KEY is REQUIRED. Generate one:
#   python -c "import secrets; print(secrets.token_urlsafe(64))"
# Put it in .env.

# Firebase Auth (optional but recommended for GitHub + email/password)
# Set CORAXIS_FIREBASE_PROJECT_ID in .env, and the NEXT_PUBLIC_FIREBASE_*
# values in frontend/.env.local from the Firebase console.

coraxis init        # apply Alembic migrations
coraxis serve       # http://127.0.0.1:8000
```

### Frontend (separate terminal)

```bash
cd frontend
npm install
# copy .env.example to .env.local and fill in NEXT_PUBLIC_FIREBASE_* values
cp .env.example .env.local   # if one exists; otherwise create it
npm run dev                  # http://localhost:3000
```

Open the frontend, create the first account (it becomes the instance administrator), and add a provider key under **Settings**. Provider keys can also come from the environment — see `.env.example`.

`coraxis dev` runs both processes together and waits for the API to report healthy before starting the frontend, rather than sleeping for a fixed interval.

---

## Configuration

Every setting is a `CORAXIS_*` environment variable with a sensible default. The ones that matter:

| Variable | Default | Notes |
|---|---|---|
| `CORAXIS_SECRET_KEY` | — | **Required.** Signs JWTs and derives the credential-encryption key. |
| `CORAXIS_ENCRYPTION_KEY` | derived | Optional Fernet key for encrypting provider keys at rest. Set explicitly in production so you can rotate the signing key independently. |
| `CORAXIS_DATABASE_URL` | `sqlite+aiosqlite:///./data/coraxis.db` | Swap to `postgresql+asyncpg://…` for Postgres. |
| `CORAXIS_HOST` / `CORAXIS_PORT` | `127.0.0.1` / `8000` | Bind address. |
| `CORAXIS_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated allowlist. `*` is rejected in production. |
| `CORAXIS_ALLOW_REGISTRATION` | `true` | Set `false` after creating your accounts. |
| `CORAXIS_ENV` | `development` | `development` \| `staging` \| `production`. Production boots fail on weak secrets, wildcard CORS, open registration, or `debug=true`. |
| `CORAXIS_ACCESS_TOKEN_MINUTES` | `30` | Access token lifetime. |
| `CORAXIS_REFRESH_TOKEN_DAYS` | `14` | Refresh token lifetime. |
| `CORAXIS_FIREBASE_PROJECT_ID` | — | Firebase project id for ID-token verification. |
| `GROQ_API_KEY` / `GOOGLE_API_KEY` / `OPENAI_API_KEY` | — | Optional environment fallback keys. Per-user keys saved via the API always take precedence. |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local model endpoint. |
| `CORAXIS_RATE_LIMIT_RUNS_PER_HOUR` | `20` | Per-user run rate limit. |
| `CORAXIS_RATE_LIMIT_REQUESTS_PER_MINUTE` | `120` | Per-user request rate limit. |
| `CORAXIS_RUN_TIMEOUT_SECONDS` | `900` | Max runtime per run. |
| `CORAXIS_RUN_MAX_CONCURRENT_PER_USER` | `2` | Concurrent run cap per user. |
| `CORAXIS_MAX_SOURCES` | `8` | Max sources per research query. |
| `CORAXIS_MEMORY_ENABLED` | `true` | Semantic memory via ChromaDB. |
| `CORAXIS_CHROMA_PATH` | `./chroma_db` | ChromaDB storage directory. |
| `CORAXIS_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model. |

`coraxis check` prints the resolved configuration and verifies every dependency imports.

---

## API

All routes are under `/api/v1` and require a bearer token except `/health`, `/ready`, `/version` and the auth endpoints.

| Group | Routes |
|---|---|
| Auth | `POST /auth/register` · `/login` · `/refresh` · `/logout` · `GET /auth/me` · `/verify` · `/sessions` |
| Credentials | `GET /credentials` · `/credentials/providers` · `PUT /credentials` · `POST /credentials/test` |
| Agents | `GET /agents` · `POST /agents` · `PATCH /agents/{slug}` · `PUT /agents/{slug}/llm` |
| Teams | `GET /teams` · `POST /teams` · `PATCH /teams/{id}` · `DELETE /teams/{id}` |
| Runs | `POST /runs` · `GET /runs` · `GET /runs/{id}` · `GET /runs/{id}/events` · `GET /runs/{id}/stream` · `POST /runs/{id}/cancel` · `/retry` · `GET /runs/{id}/report.md` |
| Memory | `GET /memory/topics` · `/memory/records` · `DELETE /memory/topics/{topic}` |

Errors are [RFC 7807](https://www.rfc-editor.org/rfc/rfc7807) problem documents served as `application/problem+json`, with a stable `code` to branch on and a `detail` written for a human:

```json
{
  "type": "https://github.com/nithincodesx/Coraxis/blob/main/docs/errors.md#unauthenticated",
  "title": "Authentication Required",
  "status": 401,
  "detail": "Provide a bearer access token in the Authorization header.",
  "code": "unauthenticated",
  "instance": "/api/v1/runs",
  "request_id": "38f069b5234c4d8d",
  "hint": "POST /api/v1/auth/login to obtain one."
}
```

Interactive docs are served at `/docs` when the app is running.

---

## Development

```bash
make install     # editable install with dev extras
make migrate     # apply database migrations
make revision m="add x"   # autogenerate an Alembic migration
make lint        # ruff check
make format      # ruff format
make typecheck   # mypy
make test        # pytest
make check       # lint + format check + typecheck + test
make coverage    # tests with coverage report
make serve       # API with autoreload on :8000
make serve-prod  # API without autoreload
make frontend    # Next.js dev server on :3000
make dev         # API and frontend together
```

The test suite is split into fast unit tests and integration tests that drive the real HTTP stack against a real (temporary) database. Integration coverage includes the auth lifecycle, run lifecycle and quotas, cross-account isolation, and a sweep of every documented `GET` route asserting a stored credential is never returned.

---

## Security

- **No plaintext keys ever leave the server.** `CredentialOut` has no field capable of carrying an API key. On disk, keys are Fernet-encrypted; `key_hint` stores only a fingerprint.
- **Wildcard CORS + credentials is rejected.** `CORAXIS_CORS_ORIGINS=*` refuses to boot in production.
- **Production startup guards.** A weak `SECRET_KEY`, wildcard CORS origin, open registration, or `debug=true` cause a hard boot failure rather than running insecurely.
- **Per-user isolation.** Runs, credentials, agents, teams, and memory are all scoped to `user_id`; cross-account reads are refused (integration-tested).
- **Token rotation.** Refresh tokens are single-use; reuse invalidates the entire session family. Password changes bump `token_version`, revoking all outstanding tokens immediately.

See `docs/errors.md` for the full RFC 7807 error catalogue.

---

## Project layout

```
src/coraxis/
├── __main__.py           CLI entrypoint (serve · init · check · dev · create-user)
├── core/                 settings, security, crypto, logging, RFC 7807 errors, rate limiting
├── db/                   async engine, SQLAlchemy 2.0 models, Alembic migrations, session helpers
├── repositories/         the only code that issues database queries
├── schemas/              Pydantic request/response contracts
├── agents/               framework-free domain: prompts, task schemas, citations, tools
├── services/             orchestration · auth · runs · LLM factory · event bus · vector store
├── workers/              asyncio run runner
├── api/v1/               versioned routers, one module per resource
└── cli/                  serve · init · check · dev · create-user
tests/
├── unit/                 fast, framework-free unit tests
└── integration/          real DB + HTTP stack against a temporary database
legacy/                   pre-rewrite Streamlit code (kept for reference, not shipped)
frontend/                 Next.js App Router + typed client + Firebase Auth UI
```

---

## Tech stack

**Backend**
- FastAPI 0.115 + Uvicorn — REST API
- SQLAlchemy 2.0 async + Alembic — persistence & migrations
- CrewAI 0.80 + LiteLLM + LangChain — agent orchestration & provider abstraction
- ChromaDB + sentence-transformers (`all-MiniLM-L6-v2`) — semantic memory
- `duckduckgo-search` — web search
- Trafilatura + readability-lxml — content extraction
- Pydantic 2 + pydantic-settings — configuration & validation
- PyJWT + argon2-cffi + cryptography — auth & encrypted credentials
- firebase-admin — Firebase ID-token verification

**Frontend**
- Next.js 16 (App Router, Turbopack), React 19, TypeScript 5
- Tailwind CSS 4, `lucide-react` 1.33
- Firebase Client SDK — GitHub OAuth + email/password
- Typed API client (`frontend/src/lib/api.ts`), SSE reader with `Last-Event-ID` resume

**External services**
- Groq (default), Google Gemini, OpenAI, Ollama (local)
- Firebase Authentication

---

## Roadmap / known limits

- Token/cost accounting is not implemented (per-run spend tracking is on the backlog).
- Billing, horizontal scale-out, and multi-region are out of scope for v1; the design leaves room for each without committing to them.
- Authentication beyond single-tenant JWT + Firebase is out of scope for v1.

---

## License

MIT — see [`LICENSE`](./LICENSE). Built by [Nithin](https://github.com/nithincodesx).
