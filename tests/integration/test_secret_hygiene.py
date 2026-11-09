"""Regression guard: a stored provider key must never come back out.

This exists because of the audit's critical finding C2. The legacy API masked
the key on ``GET /api/config`` but returned it in plaintext from
``GET /api/agents``, because that handler spread the credential row into its
response with ``**ac``. One endpoint got it right and another got it wrong, and
nothing caught the difference.

So this test does not check the endpoint that was broken. It sweeps *every*
documented GET route and asserts the secret appears in none of them. A new
endpoint that leaks a credential fails here without anyone remembering to add
a case for it.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import select

pytestmark = pytest.mark.integration

#: Unmistakable, and long enough that an accidental substring match is
#: impossible. Also not a value the placeholder validator rejects.
SENTINEL_KEY = "SENTINEL-API-KEY-DO-NOT-LEAK-8f3a91c2b7d4"

#: Route templates that must not be swept: streaming responses never return,
#: and a couple of paths have no meaningful concrete substitution.
_SKIP_SUFFIXES = ("/stream",)

#: Values used to fill path parameters. Deliberately a mix of real and
#: non-existent, so both the 200 and the 404 branches are covered.
_PARAM_VALUES = {
    "slug": "researcher",
    "provider": "groq",
    "run_id": "does-not-exist",
    "team_id": "does-not-exist",
    "topic": "does-not-exist",
}


def _fill(path: str) -> str:
    """Substitute every ``{param}`` with a concrete value."""
    for name, value in _PARAM_VALUES.items():
        path = path.replace(f"{{{name}}}", value)
    return path


async def _store_credential(client: AsyncClient) -> None:
    response = await client.put(
        "/api/v1/credentials",
        json={"provider": "groq", "api_key": SENTINEL_KEY, "base_url": ""},
    )
    assert response.status_code == 200, response.text


async def test_credential_round_trips_without_disclosure(
    auth_client: AsyncClient, registered: dict
) -> None:
    """The happy path: stored, listed, and described only by a hint."""
    await _store_credential(auth_client)

    listing = await auth_client.get("/api/v1/credentials")
    assert listing.status_code == 200
    assert SENTINEL_KEY not in listing.text

    rows = listing.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["provider"] == "groq"
    assert row["has_key"] is True
    # Four characters is enough to tell two keys apart, and useless otherwise.
    assert row["key_hint"] == SENTINEL_KEY[-4:]
    assert len(row["key_hint"]) == 4


async def test_no_get_route_ever_returns_the_key(
    auth_client: AsyncClient, app: object, registered: dict
) -> None:
    """Sweep the whole documented surface, not just the endpoint that broke."""
    await _store_credential(auth_client)

    schema = app.openapi()  # type: ignore[attr-defined]
    swept = 0
    leaked: list[str] = []

    for path, operations in schema["paths"].items():
        if "get" not in operations:
            continue
        if any(path.endswith(suffix) for suffix in _SKIP_SUFFIXES):
            continue

        response = await auth_client.get(_fill(path))
        swept += 1
        if SENTINEL_KEY in response.text:
            leaked.append(f"{path} -> {response.status_code}")

    # Guard against the sweep silently covering nothing.
    assert swept >= 15, f"only swept {swept} GET routes; the schema walk is broken"
    assert not leaked, f"secret disclosed by: {', '.join(leaked)}"


async def test_provider_status_reports_the_source_without_the_secret(
    auth_client: AsyncClient, registered: dict
) -> None:
    await _store_credential(auth_client)

    response = await auth_client.get("/api/v1/credentials/providers")
    assert response.status_code == 200
    assert SENTINEL_KEY not in response.text

    groq = next(item for item in response.json() if item["provider"] == "groq")
    assert groq["configured"] is True
    assert groq["source"] == "user"
    assert groq["key_hint"] == SENTINEL_KEY[-4:]


async def test_the_key_is_encrypted_at_rest(
    auth_client: AsyncClient, registered: dict, session: object
) -> None:
    """Storing a key in plaintext would make every other guarantee moot."""
    await _store_credential(auth_client)

    from coraxis.core.crypto import decrypt
    from coraxis.db.models import ProviderCredential

    stored = (
        await session.execute(  # type: ignore[attr-defined]
            select(ProviderCredential).where(ProviderCredential.user_id == registered["user"]["id"])
        )
    ).scalar_one()

    assert SENTINEL_KEY not in stored.encrypted_key
    assert decrypt(stored.encrypted_key) == SENTINEL_KEY
    # The hint is the only part that is allowed to be readable.
    assert stored.key_hint == SENTINEL_KEY[-4:]


async def test_updating_the_base_url_does_not_require_resending_the_key(
    auth_client: AsyncClient, registered: dict, session: object
) -> None:
    """Omitting ``api_key`` must leave the stored secret untouched.

    The alternative — treating an empty string as "clear the key" — would wipe
    a working credential whenever the user edited only the model name.
    """
    await _store_credential(auth_client)

    response = await auth_client.put(
        "/api/v1/credentials",
        json={"provider": "groq", "api_key": "", "base_url": "https://example.invalid"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["has_key"] is True

    from coraxis.core.crypto import decrypt
    from coraxis.db.models import ProviderCredential

    stored = (
        await session.execute(  # type: ignore[attr-defined]
            select(ProviderCredential).where(ProviderCredential.user_id == registered["user"]["id"])
        )
    ).scalar_one()

    assert stored.base_url == "https://example.invalid"
    assert decrypt(stored.encrypted_key) == SENTINEL_KEY


async def test_one_users_key_is_invisible_to_another(
    client: AsyncClient, auth_client: AsyncClient, registered: dict, firebase_stub
) -> None:
    """Credentials are per-user; a second account sees an empty list."""
    await _store_credential(auth_client)

    second = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "other@example.com",
            "password": "a-completely-different-passphrase",
            "display_name": "Other",
        },
    )
    assert second.status_code == 201, second.text
    firebase_stub.register_token(
        second.json()["access_token"],
        "other@example.com",
        uid="firebase-uid-other",
        display_name="Other",
    )

    response = await client.get(
        "/api/v1/credentials",
        headers={"Authorization": f"Bearer {second.json()['access_token']}"},
    )
    assert response.status_code == 200
    assert response.json() == []
    assert SENTINEL_KEY not in response.text


async def test_a_placeholder_is_rejected_rather_than_stored(
    auth_client: AsyncClient, registered: dict
) -> None:
    response = await auth_client.put(
        "/api/v1/credentials",
        json={"provider": "groq", "api_key": "your-key-here", "base_url": ""},
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_unknown_provider_is_rejected(auth_client: AsyncClient, registered: dict) -> None:
    response = await auth_client.put(
        "/api/v1/credentials",
        json={"provider": "not-a-provider", "api_key": SENTINEL_KEY},
    )
    assert response.status_code == 422
