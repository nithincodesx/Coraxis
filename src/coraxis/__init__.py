"""Coraxis — autonomous multi-agent research platform.

A four-agent pipeline that decomposes a research question, searches the web,
cross-checks sources, and returns a cited markdown report.

The public surface of this package is intentionally small. Import the
application factory rather than reaching into submodules:

    from coraxis.main import create_app

Layering (each layer may only import from the ones below it):

    api/         HTTP concerns — routing, dependencies, serialisation
    workers/     background execution
    services/    business logic — orchestration, LLM access, memory
    agents/      CrewAI agent and task definitions
    repositories/  the only code that touches the database
    db/          engine, session, models, migrations
    schemas/     Pydantic DTOs crossing the HTTP boundary
    core/        configuration, logging, errors, security, crypto
"""

from __future__ import annotations

__version__ = "2.0.0"
__all__ = ["__version__"]
