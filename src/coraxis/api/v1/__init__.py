"""API version 1.

Everything under ``/api/v1``. The version prefix is in the path rather than a
header so that a breaking change can be served alongside the old contract
instead of replacing it.
"""

from __future__ import annotations

from fastapi import APIRouter

from coraxis.api.v1.endpoints import agents, auth, credentials, memory, runs, system, teams

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(auth.router)
api_router.include_router(credentials.router)
api_router.include_router(agents.router)
api_router.include_router(teams.router)
api_router.include_router(runs.router)
api_router.include_router(memory.router)

__all__ = ["api_router"]
