"""Shared test fixtures.

Each test gets its own SQLite database in a temporary directory, so tests are
fully isolated and can run in any order. The application is built fresh per
test rather than importing the module-level ``app``, which would freeze the
first test's configuration into every later one.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

#: A long, obviously-fake signing key. Set before anything imports the settings
#: module so the very first `get_settings()` call sees it.
TEST_SECRET = "test-secret-key-long-enough-for-any-validation-check"

os.environ["CORAXIS_SECRET_KEY"] = TEST_SECRET
os.environ["CORAXIS_ENV"] = "development"

REGISTER_PAYLOAD = {
    "email": "researcher@example.com",
    "password": "correct-horse-battery-staple",
    "display_name": "Test Researcher",
}


def _apply_env(monkeypatch: pytest.MonkeyPatch, db_path: Path, tmp_path: Path) -> None:
    """Point the app at a throwaway database and disable slow or external bits."""
    monkeypatch.setenv("CORAXIS_SECRET_KEY", TEST_SECRET)
    monkeypatch.setenv("CORAXIS_ENV", "development")
    monkeypatch.setenv("CORAXIS_DATABASE_URL", f"sqlite+aiosqlite:///{db_path}")
    monkeypatch.setenv("CORAXIS_CHROMA_PATH", str(tmp_path / "chroma"))
    # Semantic memory loads a sentence-transformers model; tests never need it.
    monkeypatch.setenv("CORAXIS_MEMORY_ENABLED", "false")
    # Rate limits are exercised explicitly by their own tests.
    monkeypatch.setenv("CORAXIS_RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("CORAXIS_LOG_LEVEL", "WARNING")


def _reset_caches() -> None:
    """Drop every process-wide cache so new settings actually take effect."""
    from coraxis.core.config import reset_settings_cache
    from coraxis.core.crypto import reset_crypto_cache
    from coraxis.db import session as db_session
    from coraxis.services.events import event_bus

    reset_settings_cache()
    reset_crypto_cache()
    db_session.reset_engine()
    event_bus.clear()


@pytest_asyncio.fixture
async def db_path(tmp_path: Path) -> Path:
    return tmp_path / "coraxis-test.db"


@pytest_asyncio.fixture
async def app(
    db_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[object]:
    """A freshly configured application with an empty, migrated schema."""
    _apply_env(monkeypatch, db_path, tmp_path)
    _reset_caches()

    from coraxis.db.session import create_all, dispose_engine
    from coraxis.main import create_app
    from coraxis.services.bootstrap import seed_builtin_agents
    from coraxis.services.events import event_bus

    await create_all()
    await seed_builtin_agents()

    application = create_app()
    event_bus.bind_loop(asyncio.get_running_loop())

    try:
        yield application
    finally:
        await dispose_engine()
        _reset_caches()


@pytest_asyncio.fixture
async def client(app: object) -> AsyncIterator[AsyncClient]:
    """An unauthenticated HTTP client bound to the test app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as http:
        yield http


@pytest_asyncio.fixture
async def registered(client: AsyncClient) -> dict:
    """Register the default account and return the token pair."""
    response = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert response.status_code == 201, response.text
    return response.json()


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient, registered: dict) -> AsyncClient:
    """An HTTP client authenticated as the default account."""
    client.headers["Authorization"] = f"Bearer {registered['access_token']}"
    return client


@pytest_asyncio.fixture
async def session(app: object) -> AsyncIterator[object]:
    """A database session for asserting on persisted state directly."""
    from coraxis.db.session import session_scope

    async with session_scope() as db_session:
        yield db_session


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "integration: exercises the database and HTTP stack")
    config.addinivalue_line("markers", "slow: long-running or network-dependent")
