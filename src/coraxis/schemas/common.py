"""Shared schema primitives: base classes, pagination, and datetime handling."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer

T = TypeVar("T")


def to_iso_z(value: datetime | None) -> str | None:
    """Serialise a stored naive-UTC datetime as an explicit ISO-8601 UTC string.

    Without the ``Z`` suffix a browser parses the value as *local* time, which
    silently shifts every timestamp in the UI by the client's offset.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


#: A datetime that always crosses the wire as ``...Z``.
UTCDatetime = Annotated[datetime, PlainSerializer(to_iso_z, return_type=str | None)]


class RequestModel(BaseModel):
    """Base for inbound payloads. Unknown fields are rejected, not ignored."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
    )


class ResponseModel(BaseModel):
    """Base for outbound payloads, built from ORM objects where possible."""

    model_config = ConfigDict(from_attributes=True)


class Page(ResponseModel, Generic[T]):
    """A slice of a larger collection."""

    items: list[T]
    total: int = Field(description="Total matching records, ignoring pagination.")
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class DeletedResponse(ResponseModel):
    """Uniform acknowledgement for DELETE endpoints."""

    deleted: bool = True
    id: str


class HealthResponse(ResponseModel):
    """Liveness probe result."""

    status: str
    version: str
    environment: str
    uptime_seconds: float


class ReadyCheck(ResponseModel):
    """One dependency's contribution to the readiness verdict."""

    name: str
    ok: bool
    detail: str = ""


class ReadyResponse(ResponseModel):
    """Readiness probe result."""

    ready: bool
    checks: list[ReadyCheck]
