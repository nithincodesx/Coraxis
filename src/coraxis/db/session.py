"""Async engine, session factory, and the FastAPI database dependency.

One engine per process, created lazily and disposed on shutdown. Nothing else
in the codebase constructs a session — go through :func:`session_scope` or the
:func:`get_db` dependency so transaction boundaries stay consistent.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool, StaticPool

from coraxis.core.config import Settings, get_settings
from coraxis.core.logging import get_logger
from coraxis.db.base import Base

logger = get_logger("db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def _build_engine(settings: Settings) -> AsyncEngine:
    """Construct the async engine with engine-appropriate pooling."""
    kwargs: dict[str, object] = {
        "echo": settings.db_echo,
        "pool_pre_ping": True,
    }

    if settings.is_sqlite:
        # aiosqlite runs the driver on a worker thread, so the default
        # same-thread check must be disabled.
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in settings.database_url:
            # Every session must see the same in-memory database.
            kwargs["poolclass"] = StaticPool
        else:
            # Holding pooled connections to a file keeps SQLite locks open
            # longer than necessary; opening per-session is cheaper here.
            kwargs["poolclass"] = NullPool
    else:
        kwargs["pool_size"] = settings.db_pool_size
        kwargs["max_overflow"] = settings.db_max_overflow

    engine = create_async_engine(settings.database_url, **kwargs)

    if settings.is_sqlite:

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection: object, _record: object) -> None:
            """SQLite needs these explicitly.

            ``foreign_keys`` is off by default in SQLite, which would silently
            disable every ON DELETE CASCADE in the schema. WAL plus NORMAL
            synchronous is the standard durability/throughput trade-off for a
            server-side SQLite database.
            """
            cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
            finally:
                cursor.close()

    return engine


def get_engine() -> AsyncEngine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        settings.ensure_directories()
        _engine = _build_engine(settings)
        logger.debug("database engine created for %s", _redact(settings.database_url))
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


async def dispose_engine() -> None:
    """Close pooled connections and forget the engine."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.debug("database engine disposed")
    _engine = None
    _session_factory = None


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """Transactional session for non-request code (workers, CLI, tests).

    Commits on clean exit, rolls back on any exception.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_db() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding a request-scoped session.

    The route decides when to commit; if it raises, the transaction is rolled
    back and nothing is persisted.

    Committing here instead would be the wrong fix. Dependency teardown runs
    *after* the response has been sent, so a constraint violation raised at
    that point would reach the client as a successful response whose data was
    never written. The cost of keeping the commit in the route is that
    forgetting it becomes a silent data-loss bug, so the teardown checks for
    uncommitted work and complains loudly rather than failing quietly.
    """
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        else:
            if session.new or session.dirty or session.deleted:
                logger.error(
                    "request finished with %d new, %d modified and %d deleted object(s) "
                    "uncommitted; this route is missing `await session.commit()`",
                    len(session.new),
                    len(session.dirty),
                    len(session.deleted),
                )


async def create_all() -> None:
    """Create every table directly from the models.

    For tests and first-run convenience only. Production schema changes go
    through Alembic so they are versioned and reversible.
    """
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def drop_all() -> None:
    """Drop every table. Tests only."""
    engine = get_engine()
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)


def reset_engine() -> None:
    """Forget the cached engine without awaiting disposal. Tests only."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


def _redact(url: str) -> str:
    """Hide the password in a connection string before logging it."""
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    _, _, host = rest.rpartition("@")
    return f"{scheme}://***@{host}"
