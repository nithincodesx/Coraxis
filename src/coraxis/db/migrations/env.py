"""Alembic migration environment.

The database URL comes from Coraxis settings rather than ``alembic.ini`` so
there is exactly one source of truth. Works in offline (``--sql``) and online
mode, and on both SQLite and Postgres.
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.pool import NullPool

import coraxis.db.models  # noqa: F401  -- import registers models on Base.metadata
from coraxis.core.config import get_settings
from coraxis.db.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
settings = get_settings()

# configparser treats '%' as interpolation syntax; URL-encoded passwords
# contain it frequently, so escape before handing the URL over.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

#: SQLite cannot ALTER most things in place; batch mode rewrites the table.
_RENDER_AS_BATCH = settings.is_sqlite


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=_RENDER_AS_BATCH,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_as_batch=_RENDER_AS_BATCH,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations() -> None:
    settings.ensure_directories()

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(_run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
