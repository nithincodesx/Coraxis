"""Regression tests for the 2026-11-17 audit fixes.

Three defects are pinned here:

1. Tokens issued by the local ``/auth/*`` endpoints were rejected by every
   protected route (only Firebase ID tokens were verified), so the
   documented register → use-token flow could never work.
2. ``POST /credentials/test`` and ``POST /custom-providers/test`` required
   no authentication while making outbound calls to a caller-supplied base
   URL — an open SSRF/oracle proxy. ``GET /agents/{slug}/defaults`` was
   likewise unauthenticated.
3. An agent's ``custom_provider_nickname`` existed in the database and in
   run-time resolution, but no API schema carried it, so a named custom
   provider could never actually be referenced by an agent.
"""

from __future__ import annotations

from httpx import AsyncClient

from tests.conftest import REGISTER_PAYLOAD


async def test_local_access_token_is_accepted_on_protected_routes(
    client: AsyncClient,
) -> None:
    """A token from /auth/register works on /auth/me without Firebase."""
    response = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert response.status_code == 201, response.text
    access_token = response.json()["access_token"]

    # Deliberately NOT registered with the Firebase stub: this token must be
    # accepted on its own merits as a Coraxis-issued JWT.
    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
    assert me.status_code == 200, me.text
    assert me.json()["email"] == REGISTER_PAYLOAD["email"]

    verify = await client.get(
        "/api/v1/auth/verify", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert verify.status_code == 204, verify.text


async def test_garbage_token_is_still_rejected(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert response.status_code == 401, response.text


async def test_credential_test_endpoint_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/credentials/test",
        json={"provider": "custom", "api_key": "sk-test", "base_url": "http://127.0.0.1:9/v1"},
    )
    assert response.status_code == 401, response.text


async def test_custom_provider_test_endpoint_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/custom-providers/test",
        json={
            "nickname": "probe",
            "api_key": "sk-test",
            "base_url": "http://127.0.0.1:9/v1",
            "model": "x",
        },
    )
    assert response.status_code == 401, response.text


async def test_agent_defaults_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/api/v1/agents/researcher/defaults")
    assert response.status_code == 401, response.text


async def test_agent_custom_provider_nickname_round_trip(
    auth_client: AsyncClient,
) -> None:
    """A named custom provider can be stored and referenced by an agent."""
    created = await auth_client.put(
        "/api/v1/custom-providers",
        json={
            "nickname": "my-endpoint",
            "base_url": "https://example.invalid/v1",
            "model": "some-model",
            "api_key": "sk-test-key-1234",
        },
    )
    assert created.status_code == 200, created.text
    assert created.json()["nickname"] == "my-endpoint"
    # The key itself is never returned.
    assert "sk-test-key-1234" not in created.text

    updated = await auth_client.put(
        "/api/v1/agents/researcher/llm",
        json={
            "provider": "custom",
            "model": "some-model",
            "custom_provider_nickname": "my-endpoint",
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["llm"]["custom_provider_nickname"] == "my-endpoint"

    fetched = await auth_client.get("/api/v1/agents/researcher")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["llm"]["custom_provider_nickname"] == "my-endpoint"


def test_custom_provider_llm_config_disables_drop_params() -> None:
    """B9: production custom-provider runs must not forward ``drop_params``.

    CrewAI's native OpenAI provider passes ``drop_params`` straight into
    the OpenAI SDK, which rejects it — every custom-provider run died at
    the first LLM call. The resolver must set it False for ``custom``
    while keeping the default for built-in providers.
    """
    from types import SimpleNamespace

    from coraxis.services.research import ResearchOrchestrator

    orchestrator = object.__new__(ResearchOrchestrator)

    def row(provider: str) -> SimpleNamespace:
        return SimpleNamespace(
            provider=provider,
            model="some-model",
            base_url="https://example.com/v1",
            temperature=0.2,
            max_tokens=128,
            custom_provider_nickname="",
        )

    custom = orchestrator._llm_config("researcher", row("custom"), {}, {})
    assert custom.drop_params is False

    builtin = orchestrator._llm_config("researcher", row("groq"), {}, {})
    assert builtin.drop_params is True


def test_gemini_llm_pins_v1beta_api_version() -> None:
    """B10: Gemini runs must use API version v1beta (function calling).

    google-genai defaults to ``v1``, whose endpoint rejects function
    calling, so every tool-using Gemini run failed as shipped. The
    factory must pin the native client's ``http_options.api_version``
    to ``v1beta``.
    """
    from coraxis.services.llm.factory import LLMConfig, build_llm

    llm = build_llm(
        LLMConfig(
            agent_slug="researcher",
            provider="gemini",
            model="gemini-2.5-flash",
            api_key="fake-key-for-construction",
        )
    )
    http_options = llm.client_params["http_options"]
    api_version = getattr(http_options, "api_version", None) or http_options["api_version"]
    assert api_version == "v1beta"
