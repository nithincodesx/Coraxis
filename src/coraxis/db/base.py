"""Declarative base, shared mixins, and portable column conventions."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import DateTime, MetaData
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

#: Explicit naming convention so Alembic autogenerate produces stable,
#: human-readable constraint names on both SQLite and Postgres. Without this,
#: unnamed constraints get engine-assigned names and migrations drift.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def new_id() -> str:
    """Generate a primary key. UUID4 hex keeps IDs opaque and unguessable."""
    return uuid4().hex


def utcnow() -> datetime:
    """Current UTC time as a naive datetime.

    SQLite cannot persist ``tzinfo``, so mixing aware and naive values across
    the two supported engines produces comparison bugs. Everything is stored
    naive-UTC and re-attached on serialisation (see ``schemas.common.UTCDatetime``).
    """
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    """Base class for every ORM model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """A 32-character hex string primary key."""

    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)


class TimestampMixin:
    """``created_at`` / ``updated_at`` maintained in Python.

    Python-side defaults rather than ``server_default=func.now()`` so that both
    engines behave identically and values are always UTC.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, nullable=False, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
