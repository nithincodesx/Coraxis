"""Integration tests for the model-catalogue endpoint.

The endpoint delegates to :func:`coraxis.services.llm.discovery.list_provider_models`,
which is unit-tested in :mod:`tests.unit.test_discovery`. These tests cover the
request/response contract only.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.integration


async def test_models_endpoint_returns_provider_catalogue(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A request with an api key returns the live catalogue."""
    from coraxis.api.v1.endpoints import credentials as credentials_endpoint

    async def _fake_list(provider, api_key="", base_url=""):
        assert provider == "custom"
        assert api_key == "sk-disco"
        assert base_url == "https://api.example/v1"
        return ["mercury-2", "mercury-3"], ""

    monkeypatch.setattr(credentials_endpoint, "list_provider_models", _fake_list)

    response = await auth_client.post(
        "/api/v1/credentials/models",
        json={"provider": "custom", "api_key": "sk-disco", "base_url": "https://api.example/v1"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["models"] == ["mercury-2", "mercury-3"]
    assert body["error"] == ""
    assert body["live"] is True


async def test_models_endpoint_error_propagates(
    auth_client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovery errors surface as an error flag, not a 500."""
    from coraxis.api.v1.endpoints import credentials as credentials_endpoint

    async def _fake_list(provider, api_key="", base_url=""):
        return [], "The provider rejected this API key."

    monkeypatch.setattr(credentials_endpoint, "list_provider_models", _fake_list)

    response = await auth_client.post(
        "/api/v1/credentials/models",
        json={"provider": "custom", "api_key": "sk-bad", "base_url": "https://api.example/v1"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["models"] == []
    assert body["live"] is False
