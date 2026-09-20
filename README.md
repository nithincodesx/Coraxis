# Coraxis — Autonomous Multi-Agent Research Platform

> Four specialised agents research a topic end to end: decompose the question, search, fetch and cross-check sources, score claims, and hand back a cited report. Watch it happen live. Runs on a free stack — Groq, Gemini or a local Ollama model.

Coraxis 2.0 is a ground-up rebuild. The previous version was a Streamlit app that
had grown a FastAPI shim, a global singleton that allowed exactly one run per
server, no authentication, and an endpoint that returned stored API keys in
plaintext. The audit that drove this rewrite is in [`AUDIT.md`](./AUDIT.md); the
design decisions are in [`ARCHITECTURE_DOCUMENTATION.md`](./ARCHITECTURE_DOCUMENTATION.md).

---

## What it does

- **Four-agent sequential pipeline** — Researcher → Web Searcher → Synthesis Analyst → Report Writer, each with its own prompt, tools and model.
- **Live progress you can actually resume** — every event is persisted with a monotonic sequence number before it is broadcast, so a dropped connection replays exactly what was missed instead of starting over.
- **Citations that don't drift** — reference numbers are assigned once, at first sight, and never recomputed. A saved report keeps the same `[^n]` numbering it had when it was written.
- **Multi-user by default** — accounts, Argon2id password hashing, short-lived access tokens with rotating refresh tokens, and per-user quotas.
- **Credentials encrypted at rest** — provider keys are Fernet-encrypted with a key derived from the server secret. The API returns only the last four characters, and no response schema has a field capable of carrying a key.
- **Semantic memory** — findings are embedded into a per-user ChromaDB collection so later runs can recall earlier work, with a relational mirror so the index can be rebuilt.
- **Custom agents and teams** — define your own agents, compose them into teams, and run either the default pipeline or a saved team.

---

## Architecture

```
src/coraxis/
├── core/            config · structured logging · RFC 7807 errors · crypto · JWT · rate limiting
├── db/              SQLAlchemy 2.0 models · async session · Alembic migrations
├── repositories/    the only code that touches the database
├── schemas/         Pydantic request/response contracts
├── agents/          framework-free domain: prompts, task schemas, citations, tools
├── services/        orchestration · auth · runs · LLM factory · event bus · vector store
├── workers/         asyncio run runner
├── api/v1/          versioned routers, one module per resource
└── cli/             serve · init · check · dev · create-user
```

Imports point one way only: `api → services → repositories → db`, with `agents/`
sitting beside `services/` as a pure domain layer that imports neither the web
framework nor the database. That is what lets the pipeline be unit-tested
without an HTTP client, and what made it possible to delete Streamlit entirely
instead of mocking it.

The frontend is a Next.js app whose data layer is a single typed client
(`frontend/src/lib/api.ts`) over `/api/v1`. It holds no business logic.

---

## Quick start

Requires Python 3.11+ and Node 18+.

```bash
git clone https://github.com/nithincodesx/Coraxis.git
cd Coraxis

# Backend
python -m venv .venv
source .venv/Scripts/activate     # Windows; use .venv/bin/activate on Unix
pip install -e ".[dev]"

cp .env.example .env
# Set CORAXIS_SECRET_KEY to a long random string:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"

coraxis init                      # apply database migrations
coraxis serve                     # http://127.0.0.1:8000

# Frontend (separate terminal)
cd frontend && npm install && npm run dev   # http://localhost:3000
```

Then open the frontend, create the first account (it becomes the instance
administrator), and add a provider key under **Settings**. Provider keys can
also come from the environment — see `.env.example`.

`coraxis dev` runs both processes together and waits for the API to report
healthy before starting the frontend, rather than sleeping for a fixed interval
and hoping.

---

## Configuration

Every setting is a `CORAXIS_*` environment variable with a sensible default. The
ones that matter:

| Variable | Default | Notes |
|---|---|---|
| `CORAXIS_SECRET_KEY` | — | **Required.** Signs JWTs and derives the credential-encryption key. |
| `CORAXIS_ENCRYPTION_KEY` | derived | Set this to decouple encryption from `SECRET_KEY`, so rotating the signing key does not orphan stored credentials. |
| `CORAXIS_DATABASE_URL` | `sqlite+aiosqlite:///./data/coraxis.db` | Swap to `postgresql+asyncpg://…` for Postgres. |
| `CORAXIS_CORS_ORIGINS` | `http://localhost:3000` | Comma-separated allowlist. `*` is rejected in production. |
| `CORAXIS_ALLOW_REGISTRATION` | `true` | Rejected in production; set `false` after creating your accounts. |

In production the app refuses to boot on a weak `SECRET_KEY`, a wildcard CORS
origin, open registration, or `CORAXIS_DEBUG=true`. Failing at startup is
preferable to running insecurely and looking healthy.

`coraxis check` prints the resolved configuration and verifies every dependency
imports.

---

## API

All routes are under `/api/v1` and require a bearer token except `/health`,
`/ready`, `/version` and the auth endpoints.

| Group | Routes |
|---|---|
| Auth | `POST /auth/register` · `/login` · `/refresh` · `/logout` · `GET /auth/me` · `/sessions` |
| Credentials | `GET /credentials` · `/credentials/providers` · `PUT /credentials` · `POST /credentials/test` |
| Agents | `GET /agents` · `POST /agents` · `PATCH /agents/{slug}` · `PUT /agents/{slug}/llm` |
| Teams | `GET /teams` · `POST /teams` · `PATCH /teams/{id}` · `DELETE /teams/{id}` |
| Runs | `POST /runs` · `GET /runs` · `GET /runs/{id}` · `GET /runs/{id}/events` · `GET /runs/{id}/stream` · `POST /runs/{id}/cancel` · `/retry` · `GET /runs/{id}/report.md` |
| Memory | `GET /memory/topics` · `/memory/records` · `DELETE /memory/topics/{topic}` |

Errors are [RFC 7807](https://www.rfc-editor.org/rfc/rfc7807) problem documents
served as `application/problem+json`, with a stable `code` to branch on and a
`detail` written for a human:

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
make migrate     # apply migrations
make lint        # ruff check
make format      # ruff format
make typecheck   # mypy
make test        # pytest
make check       # lint + format check + typecheck + test
```

The test suite is split into fast unit tests and integration tests that drive the
real HTTP stack against a real (temporary) database. Integration coverage
includes the auth lifecycle, run lifecycle and quotas, cross-account isolation,
and a sweep of every documented `GET` route asserting a stored credential is
never returned.

---

## License

MIT — see [LICENSE](./LICENSE). Built by [nithincodesx](https://github.com/nithincodesx).
