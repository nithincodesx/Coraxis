"""Tests for live model catalogue discovery.

These are pure unit tests: no network, no LLM. A fake :class:`httpx.AsyncClient`
returns canned responses so every branch of :func:`list_provider_models` is
exercised deterministically.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from coraxis.core.errors import ConfigurationError
from coraxis.services.llm.discovery import list_provider_models


class _FakeResponse:
    """A minimal httpx.Response stand-in."""

    def __init__(self, *, status_code: int, payload: object, text: str = "") -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self) -> object:
        if isinstance(self._payload, str):
            raise ValueError("No JSON object could be decoded")
        return self._payload


class _FakeClient:
    """An httpx.AsyncClient stand-in that returns one canned response."""

    def __init__(self, *, timeout=None, response: _FakeResponse | None = None) -> None:
        self.timeout = timeout
        self.response = response or _FakeResponse(
            status_code=200, payload={"data": [{"id": "mercury-3"}, {"id": "mercury-2"}]}
        )
        self.captured: dict[str, Any] | None = None

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def get(
        self, url: str, *, headers: dict | None = None, params: dict | None = None
    ) -> _FakeResponse:
        self.captured = {"url": url, "headers": headers, "params": params}
        return self.response


def _patch_client(monkeypatch: pytest.MonkeyPatch, response: _FakeResponse) -> _FakeClient:
    client = _FakeClient(response=response)
    monkeypatch.setattr(
        "coraxis.services.llm.discovery.httpx.AsyncClient",
        lambda **kw: client,
    )
    return client


# ── OpenAI-compatible catalogue ─────────────────────────────────────────


async def test_openai_compatible_catalogue_parses_data_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        status_code=200,
        payload={"data": [{"id": "mercury-3"}, {"id": "mercury-2"}, {"id": "gpt-4o-mini"}]},
    )
    client = _patch_client(monkeypatch, response)

    models, error = await list_provider_models(
        "custom", api_key="sk-abc", base_url="https://api.example/v1"
    )

    assert error == ""
    assert models == ["gpt-4o-mini", "mercury-2", "mercury-3"]
    assert client.captured is not None
    assert client.captured["url"].endswith("/models")
    assert client.captured["headers"] == {"Authorization": "Bearer sk-abc"}


async def test_chat_models_sorted_first_and_non_chat_filtered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = _FakeResponse(
        status_code=200,
        payload={
            "data": [
                {"id": "text-embedding-3-small"},
                {"id": "mercury-3"},
                {"id": "whisper-1"},
                {"id": "mercury-2"},
            ]
        },
    )
    _patch_client(monkeypatch, response)

    models, error = await list_provider_models(
        "custom", api_key="sk-abc", base_url="https://api.example/v1"
    )

    assert error == ""
    # Chat models first, sorted; non-chat dropped but kept as fallback if all filtered.
    assert models == ["mercury-2", "mercury-3"]


async def test_when_all_filtered_raw_list_returned(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        status_code=200,
        payload={"data": [{"id": "text-embedding-3-small"}, {"id": "whisper-1"}]},
    )
    _patch_client(monkeypatch, response)

    models, error = await list_provider_models(
        "custom", api_key="sk-abc", base_url="https://api.example/v1"
    )

    assert error == ""
    assert models == ["text-embedding-3-small", "whisper-1"]


# ── Errors ──────────────────────────────────────────────────────────────


async def test_unauthorized_returns_key_error(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(status_code=401, payload={"error": {"message": "bad key"}})
    _patch_client(monkeypatch, response)

    models, error = await list_provider_models(
        "custom", api_key="sk-bad", base_url="https://api.example/v1"
    )

    assert models == []
    assert error == "The provider rejected this API key."


async def test_missing_api_key_rejected_before_network(monkeypatch: pytest.MonkeyPatch) -> None:
    models, error = await list_provider_models(
        "custom", api_key="", base_url="https://api.example/v1"
    )

    assert models == []
    assert error == "Enter an API key first — the provider needs it to list models."


async def test_missing_base_url_returns_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models, error = await list_provider_models("custom", api_key="sk-abc", base_url="")

    assert models == []
    assert "needs a base URL" in error


async def test_timeout_returned_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(
        response=None,
    )

    async def _boom(*args, **kwargs):
        raise httpx.TimeoutException("read timed out")

    client.get = _boom  # type: ignore[method-assign]
    monkeypatch.setattr("coraxis.services.llm.discovery.httpx.AsyncClient", lambda **kw: client)

    models, error = await list_provider_models(
        "custom", api_key="sk-abc", base_url="https://api.example/v1"
    )

    assert models == []
    assert "did not respond in time" in error


async def test_non_json_returned_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(status_code=200, payload="not json", text="not json")
    _patch_client(monkeypatch, response)

    models, error = await list_provider_models(
        "custom", api_key="sk-abc", base_url="https://api.example/v1"
    )

    assert models == []
    assert error == "The provider returned a response that is not JSON."


async def test_empty_models_returned_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(status_code=200, payload={"data": []})
    _patch_client(monkeypatch, response)

    models, error = await list_provider_models(
        "custom", api_key="sk-abc", base_url="https://api.example/v1"
    )

    assert models == []
    assert "no models" in error


# ── Gemini ──────────────────────────────────────────────────────────────


async def test_gemini_uses_query_param_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    response = _FakeResponse(
        status_code=200,
        payload={"models": [{"name": "models/gemini-2.5-flash"}]},
    )
    client = _patch_client(monkeypatch, response)

    models, error = await list_provider_models("gemini", api_key="AIza-abc", base_url="")

    assert error == ""
    assert models == ["gemini-2.5-flash"]
    assert client.captured is not None
    assert client.captured["params"] == {"key": "AIza-abc"}
    assert client.captured["headers"] == {}


# ── Configuration ───────────────────────────────────────────────────────


async def test_catalogue_url_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    from coraxis.services.llm.discovery import _catalogue_url

    assert _catalogue_url("gemini", "") == "https://generativelanguage.googleapis.com/v1beta/models"
    assert (
        _catalogue_url("custom", "https://api.inceptionlabs.ai/v1")
        == "https://api.inceptionlabs.ai/v1/models"
    )

    with pytest.raises(ConfigurationError):
        _catalogue_url("custom", "")
