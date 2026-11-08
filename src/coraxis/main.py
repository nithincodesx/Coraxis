"""Application factory and lifespan.

``create_app`` is the single entry point. Import it, configure it, and hand it
to an ASGI server:

    uvicorn coraxis.main:app

Nothing here reads the environment at import time beyond what
:func:`get_settings` already validates, so the module is safe to import from
tests, the CLI, and Alembic alike.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from coraxis import __version__
from coraxis.api.middleware import RateLimitMiddleware, RequestContextMiddleware
from coraxis.api.v1 import api_router
from coraxis.api.v1.endpoints import system
from coraxis.core.config import Settings, get_settings
from coraxis.core.errors import ConfigurationError, register_exception_handlers
from coraxis.core.firebase import initialize_firebase
from coraxis.core.logging import configure_logging, get_logger
from coraxis.db.session import dispose_engine, get_session_factory
from coraxis.services.bootstrap import run_startup_tasks
from coraxis.services.events import event_bus
from coraxis.workers import run_runner

TAGS_METADATA = [
    {"name": "system", "description": "Health, readiness, and version information."},
    {"name": "auth", "description": "Accounts, sign-in, and session management."},
    {"name": "credentials", "description": "Provider API keys, stored encrypted."},
    {"name": "agents", "description": "Agent roles and per-agent model configuration."},
    {"name": "teams", "description": "Multi-agent teams and their workflows."},
    {"name": "runs", "description": "Submitting research runs and streaming their progress."},
    {"name": "memory", "description": "Findings retained from previous runs."},
]

DESCRIPTION = """
Coraxis runs a four-agent research pipeline — Researcher, Web Searcher, Analyst,
and Report Writer — and returns a cited markdown report.

**Authentication.** Every endpoint below except the system probes requires a
bearer access token. Obtain one from `POST /api/v1/auth/register` or
`POST /api/v1/auth/login`.

**Errors.** Failures return `application/problem+json` (RFC 7807) with a
`code`, a human-readable `detail`, and a `request_id` to quote in a bug report.

**Live progress.** `GET /api/v1/runs/{run_id}/stream` is a server-sent event
stream. Send `Last-Event-ID` on reconnect to resume exactly where you left off.
"""


async def _assert_schema_ready() -> None:
    """Fail fast with an actionable message when migrations have not run.

    Silently creating tables on startup hides schema drift until it corrupts
    something, so this refuses to boot instead.
    """
    factory = get_session_factory()
    try:
        async with factory() as session:
            await session.execute(text("SELECT 1 FROM users LIMIT 1"))
    except Exception as exc:
        raise ConfigurationError(
            "The database schema is missing or out of date. Run:\n\n"
            "    alembic upgrade head\n\n"
            f"Underlying error: {type(exc).__name__}: {str(exc)[:200]}"
        ) from exc


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown.

    Startup is ordered deliberately: logging first so everything after it is
    observable, then the schema check (fail fast), then seeding and recovery.
    Shutdown drains in-flight runs before disposing the engine — closing the
    engine first would leave every running task holding a dead connection.
    """
    settings = get_settings()
    configure_logging(settings.log_level, json_output=settings.log_json)
    logger = get_logger("app")

    logger.info("starting Coraxis %s (env=%s)", __version__, settings.env)

    settings.ensure_directories()
    event_bus.bind_loop(asyncio.get_running_loop())
    initialize_firebase()

    await _assert_schema_ready()
    await run_startup_tasks()

    logger.info("ready on http://%s:%d", settings.host, settings.port)

    try:
        yield
    finally:
        logger.info("shutting down")
        await run_runner.shutdown()
        await dispose_engine()
        logger.info("stopped")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application."""
    settings = settings or get_settings()

    app = FastAPI(
        title="Coraxis API",
        description=DESCRIPTION,
        version=__version__,
        openapi_tags=TAGS_METADATA,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        contact={"name": "Nithin", "url": "https://github.com/nithincodesx"},
        license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
    )

    # Middleware runs in reverse registration order, so the request context
    # (which sets the request id) must be added last to wrap everything.
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "Last-Event-ID"],
        expose_headers=["X-Request-ID", "X-Response-Time-ms", "X-RateLimit-Remaining"],
        max_age=600,
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    # Probes at the conventional root paths, and the full API under /api/v1.
    app.include_router(system.router)
    app.include_router(api_router, prefix=settings.api_prefix)

    return app


#: Module-level app for `uvicorn coraxis.main:app`.
app = create_app()
