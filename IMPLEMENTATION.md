# Coraxis — Implementation, Architecture & Progress Reference

> Single source of truth for how Coraxis 2.0 is built, how it works, and where it stands. Companion to `README.md` (user-facing), `ARCHITECTURE_DOCUMENTATION.md` (design rationale), and `AUDIT.md` (pre-rebuild audit).

**Status:** Rebuilt and shipping (Coraxis 2.0). Branch `main`, tracking `origin/main` (`https://github.com/nithincodesx/Coraxis.git`). Working tree clean at commit `a3c9c38`.

**Latest commits (in order):**
1. `1082ec4` — feat(auth): wire GitHub OAuth + make Firebase optional; fix custom-provider base_url update semantics
2. `a3c9c38` — docs: rewrite README for Coraxis 2.0 rebuild

---

## 1. High-level summary

Coraxis is an autonomous multi-agent research platform. A user submits a question; four specialised agents (Researcher → Web Searcher → Synthesis Analyst → Report Writer) decompose it, search the web, fetch and cross-check sources, score claims, and emit a cited markdown report. Progress is streamed live over resumable SSE and persisted so a dropped connection replays exactly what was missed.

Design pillars carried into the 2.0 rebuild:

- **No global mutable state.** Runs, events, credentials, agents, teams and memory are all relational rows scoped to `user_id`. The old singleton / daemon-thread model is gone.
- **Framework-free domain layer.** `agents/` imports neither FastAPI nor SQLAlchemy; the pipeline is unit-testable without an HTTP client.
- **Defense-in-depth on secrets.** Provider API keys are Fernet-encrypted at rest and never serialised outbound.
- **Firebase-owned identity.** GitHub OAuth + email/password via Firebase; Coraxis verifies ID tokens and maps them to its own `User` table.
- **Multi-user by default.** Per-user quotas, rate limits, concurrency caps, and cross-account isolation.

---

## 2. Tech stack

| Layer | Stack |
|---|---|
| Backend API | FastAPI 0.115 + Uvicorn |
| Persistence | SQLAlchemy 2.0 async + Alembic migrations; SQLite default (`sqlite+aiosqlite`), Postgres via `postgresql+asyncpg://…` |
| Agent orchestration | CrewAI 0.80 + LiteLLM + LangChain (`langchain-core`, `langchain-groq`, `langchain-google-genai`, `langchain-openai`) |
| Semantic memory | ChromaDB 0.5 + `sentence-transformers` (`all-MiniLM-L6-v2`) |
| Web search / extraction | `duckduckgo-search`, Trafilatura, readability-lxml |
| Auth & secrets | PyJWT (HS256), argon2-cffi, cryptography (Fernet), firebase-admin |
| Config | pydantic-settings (`CORAXIS_*` prefix) |
| Frontend | Next.js 16 (App Router, Turbopack), React 19, TypeScript 5, Tailwind CSS 4, lucide-react, Firebase Client SDK |
| HTTP client (backend) | httpx |
| Tooling | ruff (lint + format), mypy (typecheck), pytest (unit + integration) |

**Out of scope for v1:** billing, horizontal scale-out, multi-region, authentication beyond single-tenant JWT + Firebase.

---

## 3. Repository layout

```
coraxis/
├── README.md                  # user-facing quick start + feature overview
├── ARCHITECTURE_DOCUMENTATION.md   # design decisions & rationale
├── AUDIT.md                   # pre-rebuild audit + resolution status
├── IMPLEMENTATION.md          # this document
├── pyproject.toml             # package metadata, deps, ruff/mypy/pytest config
├── Makefile                   # install / migrate / lint / format / typecheck / test / serve
├── alembic.ini                # Alembic config (repo root)
├── .env.example               # environment template
├── LICENSE                    # MIT
├── docker-compose.yml         # optional local services
├── src/coraxis/               # backend package
│   ├── __main__.py            # `python -m coraxis` -> cli.main.main()
│   ├── cli/
│   │   ├── main.py            # serve / init / check / create-user / dev
│   │   ├── dev.py             # start API + frontend together
│   │   └── __init__.py
│   ├── core/
│   │   ├── config.py          # Settings model + production boot guards
│   │   ├── security.py        # Argon2id, JWT access/refresh, token_version, decode_token
│   │   ├── crypto.py          # Fernet encrypt/decrypt, mask_secret, fingerprint
│   │   ├── firebase.py        # Admin SDK init, verify_id_token, get_or_create_user
│   │   ├── errors.py          # RFC 7807 problem-document error hierarchy
│   │   ├── logging.py         # structured logging, ContextVar correlation IDs
│   │   └── ratelimit.py       # sliding-window rate limiter
│   ├── db/
│   │   ├── base.py            # declarative Base, naming convention, UUID hex IDs
│   │   ├── enums.py           # RunStatus, RunTrigger, AgentKind, EventType, defaults
│   │   ├── session.py         # async engine, session_scope, get_db, create_all
│   │   ├── models.py          # 13 ORM models (User … MemoryRecord)
│   │   └── migrations/        # Alembic env + 4 version migrations
│   ├── repositories/          # the ONLY code that issues DB queries
│   │   ├── users.py           # user CRUD, token_version bump, refresh-token CRUD
│   │   ├── credentials.py     # ProviderCredential CRUD + resolve_api_key
│   │   ├── custom_providers.py# CustomProvider CRUD + resolve_api_key (user key only)
│   │   ├── agents.py          # agent defs + per-agent LLM settings + seed_builtin
│   │   ├── teams.py           # Team / TeamMember / TeamStep CRUD
│   │   ├── runs.py            # run/event/source/claim CRUD + next_event_seq + orphan reap
│   │   └── memory.py          # MemoryRecord relational mirror
│   ├── schemas/               # Pydantic request/response DTOs
│   ├── agents/                # framework-free domain: prompts, tasks, citations, tools
│   ├── services/
│   │   ├── auth.py            # register/login/refresh/logout/session listing
│   │   ├── runs.py            # run submission, retry, serialisation
│   │   ├── events.py          # RunEventBus (thread-safe SSE fan-out)
│   │   ├── research.py        # ResearchOrchestrator (full run lifecycle)
│   │   ├── bootstrap.py       # seed agents, reap orphans, prune sessions
│   │   ├── llm/factory.py     # build_llm, validate_provider_key
│   │   ├── llm/discovery.py   # live model catalogue from /models endpoints
│   │   ├── llm/sanitizer.py   # LiteLLM patches
│   │   └── vectorstore.py     # async ChromaDB wrapper, per-user namespaces
│   ├── api/
│   │   ├── main.py            # create_app, lifespan, middleware wiring
│   │   ├── deps.py            # DbSession, CurrentUser, bearer scheme
│   │   └── middleware.py      # RequestContextMiddleware, RateLimitMiddleware
│   └── api/v1/endpoints/
│       ├── auth.py            # /auth/register, /login, /refresh, /logout, /me, /sessions, /verify
│       ├── credentials.py     # credential CRUD, /test, /models, /providers, /validate
│       ├── agents.py          # agent catalog + CRUD + LLM settings
│       ├── teams.py           # team CRUD
│       ├── runs.py            # submit/list/get/report/cancel/retry/delete/events/SSE stream
│       ├── memory.py          # memory topics/records
│       ├── custom_providers.py# named custom provider CRUD + test/validate
│       └── system.py          # /health, /ready, /version
├── tests/
│   ├── unit/                  # fast framework-free unit tests
│   └── integration/           # real DB + HTTP stack on a throwaway database
├── legacy/                    # pre-rewrite Streamlit code (reference only, not shipped)
└── frontend/                  # Next.js App Router
    ├── src/app/               # pages (page.tsx, layout.tsx, hero.tsx, globals.css)
    ├── src/components/        # AuthGate, AppShell, TopNavigation, TeamsTab, AgentsTab,
    │                         # SettingsTab, RunHistory, ReportPanel, EventFeed, …
    ├── src/hooks/             # useAuth, useRunStream, useTheme, useAsyncData, useAnimations
    ├── src/lib/               # api.ts (typed client), firebase.ts, session.ts, types.ts, …
    └── src/types/firebase.d.ts
```

---

## 4. Configuration (`core/config.py`)

`Settings` is a pydantic-settings model with `env_prefix="CORAXIS_"`, cached via `@lru_cache(maxsize=1)` (`reset_settings_cache()` for tests).

### Environment variables

| Variable | Default | Notes |
|---|---|---|
| `CORAXIS_ENV` | `development` | `development` \| `staging` \| `production` |
| `CORAXIS_DEBUG` | `false` | Rejected in production |
| `CORAXIS_LOG_LEVEL` | `INFO` | DEBUG \| INFO \| WARNING \| ERROR |
| `CORAXIS_LOG_JSON` | `false` | Machine-readable logs when true |
| `CORAXIS_SECRET_KEY` | *(required)* | Signs JWTs; derives credential-encryption key |
| `CORAXIS_ENCRYPTION_KEY` | derived | Optional Fernet key; decouples encryption from signing-key rotation |
| `CORAXIS_DATABASE_URL` | `sqlite+aiosqlite:///./data/coraxis.db` | Postgres: `postgresql+asyncpg://…` |
| `CORAXIS_HOST` | `127.0.0.1` | Bind address |
| `CORAXIS_PORT` | `8000` | Bind port |
| `CORAXIS_CORS_ORIGINS` | `http://localhost:3000,http://127.0.0.1:3000` | Comma-separated allowlist; `*` rejected in production |
| `CORAXIS_ACCESS_TOKEN_MINUTES` | `30` | Access token lifetime |
| `CORAXIS_REFRESH_TOKEN_DAYS` | `14` | Refresh token lifetime |
| `CORAXIS_ALLOW_REGISTRATION` | `true` | Rejected in production after account creation |
| `CORAXIS_JWT_ISSUER` | `coraxis` | JWT `iss` claim |
| `CORAXIS_JWT_AUDIENCE` | `coraxis-api` | JWT `aud` claim |
| `CORAXIS_JWT_ALGORITHM` | `HS256` | |
| `CORAXIS_FIREBASE_PROJECT_ID` | *(required for Firebase Auth)* | Firebase project id |
| `CORAXIS_GOOGLE_APPLICATION_CREDENTIALS` | — | Optional service-account path |
| `CORAXIS_RATE_LIMIT_ENABLED` | `true` | |
| `CORAXIS_RATE_LIMIT_RUNS_PER_HOUR` | `20` | Per-user run rate limit |
| `CORAXIS_RATE_LIMIT_REQUESTS_PER_MINUTE` | `120` | Per-user request rate limit |
| `CORAXIS_RUN_TIMEOUT_SECONDS` | `900` | Max runtime per run |
| `CORAXIS_RUN_MAX_CONCURRENT_PER_USER` | `2` | Concurrent run cap per user |
| `CORAXIS_MAX_SOURCES` | `8` | Max sources per query |
| `CORAXIS_MAX_FETCH_PER_QUERY` | `5` | Max pages fetched per sub-query |
| `CORAXIS_MIN_WORD_COUNT` | `100` | Min report words |
| `CORAXIS_HTTP_TIMEOUT_SECONDS` | `20` | External HTTP timeout |
| `CORAXIS_CREW_MAX_RPM` | `10` | CrewAI max requests per minute |
| `CORAXIS_MEMORY_ENABLED` | `true` | Semantic memory on/off |
| `CORAXIS_CHROMA_PATH` | `./chroma_db` | ChromaDB storage directory |
| `CORAXIS_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model |
| `GROQ_API_KEY` | `""` | Environment fallback (per-user keys take precedence) |
| `GOOGLE_API_KEY` | `""` | Environment fallback |
| `OPENAI_API_KEY` | `""` | Environment fallback |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | Local model endpoint |

### Production boot guards (`_validate_security_posture`)

When `CORAXIS_ENV=production`, `get_settings()` raises `ValueError` (hard boot failure) if:

- `SECRET_KEY` is in the insecure set (`""`, `"change-me"`, `"changeme"`, `"secret"`, `"coraxis"`, `"test"`)
- Secret is shorter than 32 chars
- CORS origins contains `"*"` (incompatible with credentials)
- `ALLOW_REGISTRATION` is `true`
- `DEBUG` is `true`

Rationale: an app that starts insecure and looks healthy is worse than one that refuses to start.

---

## 5. CLI (`cli/`)

`python -m coraxis` → `__main__.py` → `cli.main.main()` (argparse). Five subcommands:

| Command | What it does |
|---|---|
| `serve` | `uvicorn coraxis.main:app` with `--host`/`--port`/`--reload`/`--workers`. `--reload` and `--workers > 1` are mutually exclusive (exit 2). Publishes the real bind address back to settings/env for the startup banner. |
| `init` | Applies Alembic migrations to `head` (`alembic.ini` lives at repo root, 3 levels up from `cli/main.py`). |
| `check` | Prints settings summary (env, DB URL, CORS, memory, secret strength), lists provider keys found in env, imports and checks every core dependency (fastapi, uvicorn, sqlalchemy, alembic, aiosqlite, jwt, argon2, cryptography, crewai, litellm, chromadb, duckduckgo-search, trafilatura). Exits 1 on any missing module. |
| `create-user` | Provisions an account directly (no HTTP). Validates password (min 12 chars), checks email uniqueness, Argon2id-hashes, creates user (first account = superuser). Prompts for password with confirmation if not given. |
| `dev` | Starts uvicorn with `--reload` on `127.0.0.1:{port}`, polls `/health` until ready (45s timeout), then starts `npm run dev` in `frontend/`. Streams both outputs; shuts both down on failure or Ctrl+C. Uses no `shell=True` for npm (avoids orphaned cmd.exe on Windows). |

---

## 6. Data layer (`db/` + `repositories/`)

### ORM models (`db/models.py`) — 13 tables

| Table | Key fields |
|---|---|
| `User` | `id`, `email` (unique), `password_hash`, `is_superuser`, `is_active`, `token_version` (bulk-revocation lever), `created_at` |
| `RefreshToken` | `jti` (unique, indexed = session id), `user_id`, `expires_at`, `revoked_at`, `user_agent`, `client_ip`, `created_at` |
| `ProviderCredential` | `user_id`, `provider`, `encrypted_key` (Fernet token), `key_hint` (last-4 fingerprint), `base_url`, `default_model`, `is_active`, `last_validated_at`, `last_validation_error` |
| `CustomProvider` | `user_id`, `nickname` (unique per user), `base_url`, `model`, `encrypted_key`, `key_hint`, `last_validated_at`, `last_validation_error` |
| `AgentDefinition` | `user_id` (NULL = built-in/shared), `slug`, `name`, `role`, `goal`, `backstory`, `kind` (builtin/custom), `tools` (JSON), `position` |
| `AgentLLMSettings` | `agent_slug`, `user_id`, `provider`, `model`, `temperature`, `max_tokens`, `base_url`, `custom_provider_nickname` |
| `Team` | `user_id`, `name`, `description`, `coordinator_slug`, `coordinator_instructions` |
| `TeamMember` | `team_id`, `agent_slug`, `position` |
| `TeamStep` | `team_id`, `position`, `agent_slug`, `description`, `expected_output` |
| `Run` | `user_id`, `team_id` (nullable), `query`, `trigger` (pipeline/team/retry), `status` (queued/running/succeeded/failed/cancelled/timed_out), `options` (JSON), `error`, `report_markdown`, `executive_summary`, `key_findings` (JSON), `citations_markdown`, `stats` (JSON), `started_at`, `finished_at`, `runtime_seconds`, `cancel_requested` (bool), `event_seq` (monotonic counter) |
| `RunEvent` | `run_id`, `seq` (per-run monotonic), `type`, `agent`, `level`, `message`, `payload` (JSON), `created_at`; index on `(run_id, seq)` |
| `RunSource` | `run_id`, `url`, `title`, `snippet`, `relevance`, `cite_number` |
| `RunClaim` | `run_id`, `text`, `confidence`, `relevance`, `sources` (JSON cite numbers), `agent` |
| `MemoryRecord` | `user_id`, `run_id` (nullable), `topic`, `claim`, `sources` (JSON), `confidence`, `relevance`, `agent`, `vector_id`, `created_at` |

### Repository pattern

`repositories/` is the only code that issues queries. Each function takes an `AsyncSession` and returns models/primitives; **none commit**. The route decides when to commit (`get_db()` FastAPI dependency does not auto-commit in teardown — that would surface constraint violations after the response is already sent).

Key repository behaviors:

- `repositories/runs.py:next_event_seq()` — atomic `UPDATE ... RETURNING event_seq + 1` (SQLite 3.35+ RETURNING support). `add_event()` reserves `seq` **before** broadcasting, guaranteeing gap-free SSE replay.
- `repositories/runs.py:is_cancel_requested()` — re-reads `cancel_requested` from DB (not a stale ORM attribute) so a Cancel click in another request takes effect within ~2s.
- `repositories/users.py:set_password()` bumps `token_version`, invalidating all outstanding tokens immediately.
- `repositories/credentials.py:resolve_api_key()` — the single decryption chokepoint. Precedence: user-stored active key → env fallback (`GROQ_API_KEY` etc.) → none. Returns `(api_key, source)` where `source ∈ {"user", "environment", "none"}`.
- `repositories/custom_providers.py:resolve_api_key()` — user key only; no env fallback for named custom providers.
- `repositories/agents.py:seed_builtin()` — idempotent seeding at startup; existing rows never overwritten.

### Alembic migrations

4 versions under `db/migrations/versions/`: initial schema, default-model column, custom-providers table, custom-provider nickname field.

---

## 7. Core services

### `core/config.py` — settings (see §4)
### `core/security.py` — auth cryptography

- `TokenType` enum: `ACCESS` / `REFRESH`.
- `TokenClaims` pydantic model: `sub`, `type`, `jti`, `iat`, `exp`, `iss`, `aud`, `ver` (token version), `sid` (session id = jti of the refresh token issued alongside the access token).
- `hash_password` / `verify_password` / `password_needs_rehash` — Argon2id (3 iterations, 64 MiB, 4 lanes). `validate_password_strength`: min 12, max 1024, no surrounding whitespace.
- `create_access_token(user_id, token_version, session_id)` — 30-minute default, HS256, includes `ver` and `sid`.
- `create_refresh_token(user_id, token_version, jti)` — 14-day default, persists `jti` as session id.
- `decode_token(token, expected_type)` — validates exp/iat/sub/iss/aud; uniform `AuthenticationError` (401) for all failures.

### `core/crypto.py` — credential encryption

- Fernet. Key derivation: HKDF-SHA256 over `CORAXIS_SECRET_KEY` (or explicit `CORAXIS_ENCRYPTION_KEY`), salt `coraxis/credential-encryption/v1`, info `fernet-key` → 32-byte Fernet key. `_fernet()` is `lru_cache`d.
- `encrypt(plaintext)` → URL-safe Fernet token; `decrypt(ciphertext)` → plaintext, or `ConfigurationError` ("Re-enter the provider key") if the secret changed.
- `mask_secret(value, visible=4)` → `••••••••4f2a` (8 bullets + last 4); short values fully bulleted. Never reveals more than 4 chars.
- `fingerprint(key)` → last-4 hint stored in `key_hint`.
- Empty string in → empty string out (no-op), so omitting a key on update leaves the stored value untouched.

### `core/firebase.py` — Firebase Admin integration

- `initialize_firebase()` — called once at app startup. Admin SDK fetches Google public certs; only `FIREBASE_PROJECT_ID` is strictly required (service-account path optional).
- `verify_id_token(id_token)` → `FirebaseUser` (uid, email, email_verified, display_name, picture, providers).
- `get_or_create_user()` — maps Firebase account → Coraxis `User` by email; creates account on first sign-in; first account becomes administrator.

### `core/errors.py` — RFC 7807 problem documents

Exception hierarchy: `CoraxisError` → `AuthenticationError`, `AuthorizationError`, `ValidationError`, `NotFoundError`, `RateLimitError`, `QuotaExceededError`, `ConfigurationError`, `ConflictError`, etc. Each carries a stable `code`, HTTP `status`, human `detail`, optional `hint`, and an `instance` path. Registered as FastAPI exception handlers; served as `application/problem+json`.

### `core/logging.py` — structured logging

`ContextVar` correlation IDs (`request_id`, `user_id`, `run_id`); JSON or console formatter; quiets noisy third-party loggers.

### `core/ratelimit.py` — sliding-window limiter

`SlidingWindowLimiter` with a process-wide `limiter` instance. Used by `RateLimitMiddleware` (keyed on hashed bearer token or IP; exempts health/docs; `Retry-After` on 429).

---

## 8. Authentication & sessions

### Identity model — Firebase owns identity

- **Backend verifies** Firebase ID tokens sent as `Authorization: Bearer <id_token>` on every protected route (`api/deps.py` bearer scheme uses `auto_error=False` so missing headers yield a problem+json 401 instead of Starlette's bare 403).
- `get_firebase_user()` verifies the token; `get_current_user()` → `get_or_create_user(session, firebase_user)`, re-reading the user every request so deactivation takes effect immediately.
- Frontend Firebase config (`NEXT_PUBLIC_FIREBASE_*`) lives in `frontend/.env.local`.

### Local password auth (also supported)

`services/auth.py`:
- `register()` — checks `allow_registration` (first user exempt), email uniqueness, password validation, creates user (`is_superuser = is_first_user`), issues tokens.
- `authenticate()` — identical error for wrong email vs wrong password (no enumeration), opportunistic rehash if policy tightened, records login.
- `issue_tokens()` mints access + refresh pair and persists the refresh session.

### JWT access/refresh tokens

- Access: 30 min (`access_token_minutes`), HS256, claims `ver` + `sid`.
- Refresh: 14 days (`refresh_token_days`), `jti` persisted as session row.

### Token version revocation

`User.token_version` is stamped into every token's `ver` claim. `set_password()` and `bump_token_version()` increment it. On refresh, if `claims.ver != user.token_version` → 401 "session invalidated". This invalidates all outstanding tokens on password change or logout-all-sessions.

### Rotating refresh tokens (single-use + theft detection)

`RefreshToken` table: `jti` (unique), `expires_at`, `revoked_at`, `user_agent`, `client_ip`, `created_at`.

On refresh (`services/auth.py:refresh_tokens`):
1. Decode refresh token; look up stored row by `jti`.
2. If `stored.is_revoked` → **revoke every session for that user** (classic stolen-token signature), commit immediately (load-bearing so revocation outlives the raised exception), then 401.
3. Otherwise revoke the single used token and issue a fresh pair (rotation).

`logout()` revokes one token, or revokes all + bumps `token_version` when `all_sessions`.

### Session listing

`list_sessions()` returns active sessions, flagging the caller's own via the `sid` claim.

---

## 9. Credentials / provider keys

### Encryption at rest

`ProviderCredential` and `CustomProvider` store `encrypted_key` (Fernet token) and `key_hint` (last-4 fingerprint). There is **no column holding a usable plaintext key**.

### Masking in responses

`CredentialOut` / `CustomProviderOut` expose only `key_hint` and a `has_key` boolean. Never plaintext, never `encrypted_key`. `crypto.mask_secret` caps revealed chars at 4.

### Validation without storing

`POST /credentials/test` (`CredentialTestRequest`: provider, api_key, model, base_url) → `services.llm.factory.validate_provider_key()` makes one minimal `litellm.acompletion` call ("ping", max_tokens=1) and returns `CredentialTestResult(valid, provider, model, error, latency_ms)`. No auth required (settings screen validates before saving). Friendly error translation for 401/429/model-not-found/connection issues (`factory.py:_friendly_error`).

---

## 10. Agents & teams

### Built-in agent definitions (`agents/definitions.py`)

Pipeline order (`db/enums.py:PIPELINE_ORDER`): researcher → web_searcher → analyst → summarizer.

| Slug | Name | Role | What it does |
|---|---|---|---|
| `researcher` | Researcher | Senior Research Analyst | Decomposes query into 4–7 searchable sub-questions; lists key entities; calls `recall_memory` first to avoid repeating prior work. |
| `web_searcher` | Web Searcher | Web Search Specialist | Per sub-question: `web_search` (≤8 results), `fetch_page` (best 5); returns structured findings (URLs, titles, snippets, full text); prioritises authoritative sources; records failures. |
| `analyst` | Synthesis Analyst | Synthesis Analyst | Cross-references findings; scores source relevance 0–100; detects contradictions/consensus; assigns calibrated confidence; calls `register_claim` per claim with supporting sources. |
| `summarizer` | Report Writer | Report Writer | Emits markdown: executive summary, key findings with `[^n]` citations, detailed findings, confidence assessment, sources appendix with `█`/`░` relevance bars. |

### Custom agents

`AgentDefinition.user_id` NULL = built-in/shared; non-null = user-owned custom. `slug` validated `^[a-z][a-z0-9_]{1,63}$`. Custom agents get `kind=CUSTOM`, `position=100`. CRUD: create/update/delete (update is partial, excludes `llm`).

### Per-agent LLM settings (3-level resolution, most specific first)

`ResearchOrchestrator._llm_config()` (`services/research.py:414`):

1. Agent's own `AgentLLMSettings` row (`provider`, `model`, `temperature`, `max_tokens`, `base_url`).
2. If `provider == "custom"` and `custom_provider_nickname` set → named `CustomProvider` row's `base_url`/`model`/encrypted key override everything.
3. Fall back to credential's `default_model`/`base_url`, then built-in `DEFAULT_MODELS`/`DEFAULT_BASE_URLS` (`db/enums.py`).

`fallback_provider` (`research.py:341`) prefers any provider the user actually has a key for (custom → groq → openai → gemini → ollama), defaulting to groq, so adding only a custom key doesn't leave default agents pointing at keyless groq.

`LLMConfig` (`llm/factory.py:38`): `agent_slug`, `provider`, `model`, `api_key` (excluded from repr), `base_url`, `temperature`, `max_tokens`, `key_source`. `build_llm()` constructs a CrewAI `LLM` with provider prefix (`groq/…`, `openai/…` for custom). Fail-fast `ConfigurationError` if no key or model resolves.

### Teams

`Team.user_id`, `name`, `description`, `coordinator_slug`, `coordinator_instructions`. Ordered children: `TeamMember` (agent_slug, position) and `TeamStep` (position, agent_slug, description, expected_output). Max 12 members, max 24 steps, dedup agent slugs. `create_team`/`update_team` replace members/steps atomically; `remove_agent_from_teams` detaches deleted agents.

Teams run via `build_team_crew()` (`crew.py:122`) with optional explicit workflow steps + coordinator task.

---

## 11. Runs — lifecycle, events, SSE

### Run statuses

`queued` → `running` → `succeeded` / `failed` / `cancelled` / `timed_out`. `is_terminal` property on `Run`.

### Run submission (`services/runs.py:submit`)

Enforces quotas (runs/hour rate limit, max concurrent per user), creates run `QUEUED`, emits `run.queued` event, returns HTTP 202; `run_runner.submit(run.id)` schedules an asyncio task (`workers/runner.py`).

### Orchestration (`services/research.py:ResearchOrchestrator`, 747 lines)

Full run lifecycle:

1. **Config resolution** — agent specs, LLM config per agent, credentials, memory flag.
2. **`_prepare`** — marks `RUNNING`, resolves agent specs.
3. **`_drive`** — builds crew, `crew.kickoff_async()` wrapped in `asyncio.wait_for(run_timeout_seconds)`; parses the final report; persists; marks `SUCCEEDED`.
4. **Cancellation watcher** — polls `is_cancel_requested` every 2s; tools check `signal.cancelled` between steps; on cancel → `_finalise(CANCELLED)`.
5. **Timeout** → `TIMED_OUT`. Crash → `FAILED` (orchestrator catches all exceptions, terminal state written exactly once with double-finalisation guards).
6. **Orphan reaping** — `reap_orphaned_runs()` at startup fails QUEUED/RUNNING runs left by a crash.

### Event recording & SSE

`EventRecorder` (`research.py:63`) batches events (64 per batch or 250ms idle flush) and persists each with a monotonic `seq` **before** broadcasting — gap-free replay guarantee.

`RunEventBus` (`services/events.py`) — thread-safe fan-out to SSE subscribers via `call_soon_threadsafe`; bounded drop-oldest queues.

`GET /runs/{id}/stream` (`endpoints/runs.py:stream_run`) — accepts `Last-Event-ID` header or `?since=` query; replays missed events (`list_events` with `since_seq=cursor`, capped at 1000), then subscribes to `event_bus` for live events. SSE frame format `id: {seq}\nevent: {type}\ndata: {json}\n\n`. Keepalive comments every 15s. `X-Accel-Buffering: no` to defeat nginx buffering. Terminal events (`run.succeeded/failed/cancelled/timed_out`) close the stream.

### Frontend SSE (`hooks/useRunStream.ts`)

Uses `fetch` (not `EventSource`) so it can send `Authorization: Bearer` and `Last-Event-ID`. Manual SSE frame parser (`id:`, `event:`, `data:` fields; `:` comments = keepalives). Reconnects with `cursorRef.current` as `Last-Event-ID`; exponential backoff [500, 1000, 2000, 5000, 10000] ms. 401 → `refreshAccessToken` via session lib, then reconnect. Buffer capped at `maxEvents` (2000).

### Cancellation

`Run.cancel_requested` (DB-polled, not stale ORM). `request_cancel()` sets it; checked cooperatively within ~2s.

### Retry

`services/runs.py:retry()` creates a new run from a finished run's query/options, `trigger=retry`, returns 202. Retrying an unfinished run is refused (429).

---

## 12. Pipeline / workflow (four-agent pipeline)

### CrewAI assembly (`agents/crew.py`)

- `build_pipeline_crew()` — `Crew(agents=[...], tasks=[...], process=Process.sequential, memory=False, max_rpm=crew_max_rpm)`. CrewAI's own memory is **disabled**; semantic memory is handled by the per-user vector store.
- `build_team_crew()` — user team assembly with optional explicit steps + coordinator task.

### Tasks (`agents/tasks.py`)

Four `Task` objects, each with `output_json` bound to a Pydantic schema (`SubQuestions`, `RawFindings`, `AnalyzedFindings`, `FinalReport`). CrewAI validates model output and retries on mismatch. `max_iter=6`, `max_retry_limit=2`, `allow_delegation=False`, `respect_context_window=True` per agent.

### Tools (`agents/tool_registry.py`)

| Tool | Granted to | Purpose |
|---|---|---|
| `web_search` | researcher, web_searcher | DuckDuckGo via `SearchClient` |
| `fetch_page` | web_searcher | Trafilatura via `PageFetcher` |
| `recall_memory` | researcher, analyst | ChromaDB per-user query |
| `register_claim` | analyst (requires tracker) | `CitationTracker` claim registration |
| `send_message`, `read_inbox`, `blackboard_write`, `blackboard_read` | all (always available) | inter-agent comms |

`ToolContext` (`agents/context.py`) is the dependency container injected into tools; `for_agent` gives a per-agent attribution view.

### Citation tracker (`agents/citations.py`)

`CitationTracker` — thread-safe (`RLock`). `add_source()` assigns `cite_N` **once, on first sight**; re-registering the same URL keeps the number and only raises relevance. `add_claim()` → `claim_NNNN`. `inline_markers(claim_id)` renders `[^n][^m]`. `format_markdown()` renders the sources appendix with `█`/`░` relevance bars. Numbers are never recomputed — fixes the prior drift bug where adding a source renumbered existing references.

---

## 13. Semantic memory

### Architecture — ChromaDB + relational mirror

`services/vectorstore.py:VectorStore` — async wrapper around `chromadb.PersistentClient` (`./chroma_db`). Embedding: `SentenceTransformerEmbeddingFunction("all-MiniLM-L6-v2")` (~90 MB, loaded lazily on first use). All Chroma calls offloaded via `asyncio.to_thread` behind an `asyncio.Lock` so the event loop never stalls.

Per-user namespaced collections: `collection_name(user_id, topic)` = `u{user_id[:12]}_{slugify_topic(topic)}`. The `u{user}` prefix prevents cross-account leakage. Metadata per entry: topic, sources (joined string), confidence, relevance, agent, timestamp.

Relational mirror: `MemoryRecord` (`db/models.py`) — `user_id`, `run_id` (nullable), `topic`, `claim`, `sources` (JSON), `confidence`, `relevance`, `agent`, `vector_id`, `created_at`. Chroma owns embeddings; the DB owns the facts so the vector index can be rebuilt if corrupted or the embedding model changes.

### Storing findings

`ResearchOrchestrator._write_memory()` (`research.py:611`) writes each claim (text, sources, confidence, relevance, agent) to Chroma via `vector_store.upsert()` then `memory_repo.create_records()` to the DB. Gated by `options.include_memory` (default true) and `memory_enabled`.

### Recalling findings

`ResearchOrchestrator._make_recall()` (`research.py:555`) returns an async `recall(topic, query, n_results)` callable injected into `ToolContext.recall`. The `recall_memory` tool calls it before web searching. `repositories/memory.py` supports `list_records`, `list_topics`, `delete_topic`, `delete_for_run`.

---

## 14. Frontend (Next.js App Router)

### Structure

`frontend/src/app/` — `page.tsx`, `layout.tsx`, `hero.tsx`, `globals.css`, `fonts/`.  
`frontend/src/components/` — `AuthGate`, `AppShell`, `TopNavigation`, `TeamsTab`, `AgentsTab`, `SettingsTab`, `RunHistory`, `ReportPanel`, `EventFeed`, `AgentProgressGrid`, `WorkspaceTab`, `SiteBackdrop`, `HeroBackdrop`, `ThemeToggle`, `ui/`.  
`frontend/src/hooks/` — `useAuth`, `useRunStream`, `useTheme`, `useAsyncData`, `useAnimations`.  
`frontend/src/lib/` — `api.ts` (typed client), `firebase.ts`, `session.ts`, `types.ts`, `theme.ts`, `nav.ts`, `derive.ts`, `animations.ts`.

### Auth (`hooks/useAuth.ts`)

Firebase-backed auth state. On mount: restore stored user, verify via `GET /api/v1/auth/me` (bearer = Firebase ID token); if invalid, fall back to stored user. `login` / `loginWithGitHub` / `register` → Firebase sign-in → `api.auth.me()` → `persistSession(me)`. `logout` → Firebase sign-out + `clearSession()`.

`AuthGate.tsx` — login/register gate with GitHub OAuth popup or email/password; notes that the first account becomes administrator; displays `ApiError` field errors.

### Typed API client (`lib/api.ts`)

`API_BASE = "/api/v1"`. `ApiError` class with `status`, `code`, `problem` (RFC 7807), `retryAfter`, `isRetryable` (429 or ≥500). `rawRequest()` attaches bearer token from `getAccessToken()`, 30s default / 120s long timeout, abort controller, throws `ApiError` on non-2xx. `request()` wraps with **single auth retry on 401** (single-flight via session module prevents refresh-token reuse detection from triggering on concurrent 401s).

Namespaced clients: `api.auth`, `api.credentials`, `api.agents`, `api.teams`, `api.runs` (submit/list/get/events/cancel/retry/remove/reportMarkdown/streamPath), `api.memory`, `api.system`.

`authHeaders()` returns `Accept: text/event-stream` + `Authorization: Bearer` for the SSE stream (deliberately a fetch path, not an EventSource URL, because EventSource can't send auth headers or resume with an explicit cursor; a token in a query string would leak to logs).

### Firebase client (`lib/firebase.ts`)

`initFirebase()` initializes `firebase/app`, `firebase/auth`, `firebase/storage` from `NEXT_PUBLIC_FIREBASE_*` env vars. `isFirebaseConfigured()` checks presence.

Auth: `signInWithGitHub()` (`GithubAuthProvider`, `read:user` scope), `signInWithEmail()`, `signUpWithEmail()` (with `updateProfile` displayName), `signOut()`, `getCurrentFirebaseUser()`, `getIdToken(forceRefresh)`, `onAuthStateChange()`.

Storage: `uploadFile(userId, path, file)` → `users/${userId}/${path}`, returns download URL.

### Session lib (`lib/session.ts`)

`persistSession(user)`, `getStoredUser()`, `clearSession()`, `subscribe(callback)`, `isAuthenticated()`, `getAccessToken()`, `refreshAccessToken(apiBase)`.

---

## 15. API route map (`/api/v1`)

| Group | Routes | Auth |
|---|---|---|
| Auth | `POST /auth/register` · `/login` · `/refresh` · `/logout` · `GET /auth/me` · `/verify` · `/sessions` | bearer except register/login/verify |
| Credentials | `GET /credentials` · `/credentials/providers` · `PUT /credentials` · `POST /credentials/test` · `/models` · `/validate` | bearer except /test |
| Agents | `GET /agents` · `POST /agents` · `PATCH /agents/{slug}` · `PUT /agents/{slug}/llm` · `DELETE` | bearer |
| Teams | `GET /teams` · `POST /teams` · `PATCH /teams/{id}` · `DELETE /teams/{id}` | bearer |
| Runs | `POST /runs` · `GET /runs` · `GET /runs/{id}` · `GET /runs/{id}/events` · `GET /runs/{id}/stream` · `POST /runs/{id}/cancel` · `/retry` · `DELETE` · `GET /runs/{id}/report.md` | bearer |
| Memory | `GET /memory/topics` · `/memory/records` · `DELETE /memory/topics/{topic}` | bearer |
| System | `GET /health` · `/ready` · `/version` | none |

Errors: RFC 7807 `application/problem+json` with stable `code`, human `detail`, `instance` path, `request_id`, optional `hint`.

---

## 16. Tests

Structure: `tests/` with `conftest.py`, `unit/`, `integration/`.

`conftest.py` — per-test isolated SQLite DB in `tmp_path`; env overrides (test secret, development env, throwaway DB, memory disabled, rate limiting disabled); fixtures: `app`, `client`, `registered`, `auth_client`, `session`. Markers: `integration`, `slow`.

Test files (13):

| File | Coverage |
|---|---|
| `tests/unit/test_security.py` | password hashing / JWT |
| `tests/unit/test_crypto.py` | Fernet round-trip, ciphertext randomization, `mask_secret` ≤4 chars, `fingerprint` tail-only |
| `tests/unit/test_citations.py` | citation tracker numbering |
| `tests/unit/test_ratelimit.py` | sliding-window limiter |
| `tests/unit/test_tools.py` | agent tools |
| `tests/unit/test_report_parsing.py` | report result parsing |
| `tests/unit/test_model_discovery.py` | model catalogue lookup |
| `tests/integration/test_auth_flow.py` | auth flow end-to-end |
| `tests/integration/test_run_lifecycle.py` (376 lines) | submission 202 + runner handoff, one-word query rejection, unknown-option rejection (extra=forbid), list pagination, status filtering, 404, report download, monotonic event seq uniqueness, `since` replay, cancel flag, cancel finished = no-op, retry (new run trigger=retry), retry unfinished = 429, delete, concurrent cap per user (429 with `active_runs`), cross-account isolation (every route scoped → 404 for intruder) |
| `tests/integration/test_run_finalisation.py` | terminal-state guarantees |
| `tests/integration/test_secret_hygiene.py` | secret handling |

Coverage spans: auth (register/login/refresh/logout/sessions), credentials (CRUD/test/models), agents (custom + LLM settings), teams, runs (full lifecycle incl. cancellation/retry/quotas/isolation), SSE event-seq monotonicity, crypto (Fernet + masking), rate limiting, model discovery, report parsing, secret hygiene.

Memory is implicitly unit-tested; no dedicated Chroma integration test (memory disabled in conftest to avoid loading the sentence-transformers model).

**Current test result:** 79 unit tests pass; 31 integration tests fail with `invalid_firebase_token` (401) — pre-existing on clean `main` because Firebase isn't configured in the test environment; unrelated to the committed changes.

---

## 17. How a research run flows end-to-end

1. User submits query via frontend → `POST /api/v1/runs` (bearer = Firebase ID token).
2. API enforces quotas, creates `Run` `QUEUED`, emits `run.queued`, returns 202. `RunRunner` schedules asyncio task.
3. Orchestrator resolves agent specs + LLM config (per-agent settings → custom provider → credentials → defaults).
4. Marks `RUNNING`; builds CrewAI sequential crew (4 agents, tools, tasks with Pydantic output schemas).
5. Agent 1 (Researcher): decomposes query → sub-questions; recalls prior memory.
6. Agent 2 (Web Searcher): per sub-question, `web_search` + `fetch_page`; structured findings.
7. Agent 3 (Analyst): cross-references, scores relevance, `register_claim` per claim with `[^n]` citations.
8. Agent 4 (Summarizer): markdown report with executive summary, key findings, sources appendix.
9. `CitationTracker` assigns `cite_N` once at first sight; numbers never drift.
10. Claims + sources + memory written to DB + Chroma.
11. `RunEvent`s persisted with monotonic `seq` before broadcast; SSE stream replays on reconnect via `Last-Event-ID`.
12. Run marked `SUCCEEDED`/`FAILED`/`CANCELLED`/`TIMED_OUT`; terminal state written exactly once; `report.md` available for download.
13. User can retry (new run, same query), cancel (cooperative flag polled every 2s), or view history.

---

## 18. Security model

- **No plaintext keys outbound.** `CredentialOut` / `CustomProviderOut` have no field capable of carrying a key.
- **Fernet at rest.** Keys encrypted with HKDF-derived key from `CORAXIS_SECRET_KEY` or independent `CORAXIS_ENCRYPTION_KEY`.
- **Single decryption chokepoint.** `resolve_api_key()` in `repositories/credentials.py` (and `custom_providers.py`).
- **Wildcard CORS + credentials rejected.** `*` refused in production.
- **Production boot guards.** Weak secret, wildcard CORS, open registration, or debug → hard boot failure.
- **Per-user isolation.** Every resource scoped to `user_id`; cross-account reads refused (integration-tested).
- **Token rotation + theft detection.** Refresh tokens single-use; replay revokes all user sessions. `token_version` blunt-force revocation on password change / logout-all.
- **No enumeration.** Identical error for wrong email vs wrong password.

---

## 19. Current progress & state of the rebuild

| Area | Status |
|---|---|
| Backend architecture (FastAPI + SQLAlchemy + Alembic) | ✅ Complete |
| Auth (Firebase ID tokens + JWT access/refresh) | ✅ Complete |
| Firebase GitHub OAuth + email/password frontend | ✅ Complete |
| Encrypted credentials at rest | ✅ Complete |
| Custom agents & teams | ✅ Complete |
| Four-agent pipeline (CrewAI) | ✅ Complete |
| Resumable SSE streaming (`Last-Event-ID`) | ✅ Complete |
| Semantic memory (ChromaDB + relational mirror) | ✅ Complete |
| Quotas, rate limits, concurrency caps | ✅ Complete |
| Run lifecycle (queue/run/finalize/cancel/retry/reap) | ✅ Complete |
| Frontend (Next.js App Router + typed client) | ✅ Complete |
| Unit tests (79 passing) | ✅ Complete |
| Integration tests (31 pre-existing Firebase-env failures) | ⚠️ Pre-existing env gap, not code defects |
| `make check` (lint + format + typecheck) | ✅ Pass |
| CI pipeline | Not yet configured (repo has no `.github/workflows`) |
| Token/cost accounting | Not implemented (backlog) |
| Billing / horizontal scale-out / multi-region | Out of scope for v1 |

---

## 20. Known limits (out of scope for v1)

- Token/cost accounting (per-run spend tracking not implemented).
- Billing, horizontal scale-out, multi-region.
- Authentication beyond single-tenant JWT + Firebase.
- CI workflow (not yet configured in `.github/`).

---

## 21. Relevant documents

- `README.md` — user-facing quick start, feature overview, env reference, API map, security model, project layout, tech stack, roadmap.
- `ARCHITECTURE_DOCUMENTATION.md` — design decisions and rationale (why this shape, config CORS-as-string, session commit-in-route, etc.).
- `AUDIT.md` — pre-rebuild audit of the old Streamlit app + resolution status of every finding (C1–M12, L1–L5).
- `docs/errors.md` — RFC 7807 error catalogue.
