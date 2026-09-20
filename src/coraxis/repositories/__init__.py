"""Data access layer.

Every SQL statement in Coraxis lives in this package. Services and routes call
these functions; they never build a query themselves. That constraint is what
makes it possible to reason about authorisation — each read that should be
scoped to an owner takes ``user_id`` as its first argument.
"""

from __future__ import annotations

from coraxis.repositories import agents, credentials, memory, runs, teams, users

__all__ = ["agents", "credentials", "memory", "runs", "teams", "users"]
