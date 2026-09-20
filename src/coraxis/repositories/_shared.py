"""Small helpers shared by the repositories."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Result


def affected_rows(result: Result[Any]) -> int:
    """Number of rows an INSERT/UPDATE/DELETE touched.

    SQLAlchemy returns a ``CursorResult`` for DML, which carries ``rowcount``.
    The type mypy infers for a generic ``Result`` does not expose it, so the
    narrowing lives here rather than as a cast at every call site.
    """
    return int(getattr(result, "rowcount", 0) or 0)
