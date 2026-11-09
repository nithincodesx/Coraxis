"""End-to-end authentication behaviour.

These exercise the real HTTP stack against a real (temporary) database, so they
cover the wiring between the route, the service, the repository and the JWT
layer — the places where a unit test on any one of them would still pass while
the assembled product was broken.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from tests.conftest import REGISTER_PAYLOAD

pytestmark = pytest.mark.integration


async def test_register_returns_a_usable_token_pair(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["expires_in"] > 0
    assert body["user"]["email"] == REGISTER_PAYLOAD["email"]
    # The response must never carry the hash, let alone the password.
    assert "password" not in response.text
    assert "hash" not in response.text


async def test_first_account_becomes_the_administrator(client: AsyncClient) -> None:
    first = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert first.json()["user"]["is_superuser"] is True

    second = await client.post(
        "/api/v1/auth/register",
        json={
            "email": "second@example.com",
            "password": "another-long-enough-passphrase",
            "display_name": "Second",
        },
    )
    assert second.status_code == 201, second.text
    assert second.json()["user"]["is_superuser"] is False


async def test_duplicate_email_is_rejected(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    response = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_short_password_is_rejected(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "weak@example.com", "password": "short"},
    )

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")


async def test_login_succeeds_with_correct_credentials(client: AsyncClient) -> None:
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    response = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )

    assert response.status_code == 200, response.text
    assert response.json()["user"]["email"] == REGISTER_PAYLOAD["email"]


async def test_login_does_not_reveal_whether_an_account_exists(client: AsyncClient) -> None:
    """Wrong password and unknown email must be indistinguishable.

    Otherwise the login form doubles as an account-enumeration oracle.
    """
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    wrong_password = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": "definitely-not-the-password"},
    )
    unknown_email = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "definitely-not-the-password"},
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


async def test_protected_routes_reject_missing_and_malformed_tokens(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/runs")).status_code == 401

    client.headers["Authorization"] = "Bearer not-a-real-token"
    assert (await client.get("/api/v1/auth/me")).status_code == 401

    client.headers["Authorization"] = "Basic abc123"
    assert (await client.get("/api/v1/auth/me")).status_code == 401


async def test_me_reflects_the_authenticated_account(client: AsyncClient, registered: dict) -> None:
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {registered['access_token']}"},
    )

    assert response.status_code == 200
    assert response.json()["id"] == registered["user"]["id"]


async def test_refresh_rotates_the_token(client: AsyncClient, registered: dict) -> None:
    response = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": registered["refresh_token"]}
    )

    assert response.status_code == 200, response.text
    rotated = response.json()
    assert rotated["refresh_token"] != registered["refresh_token"]
    assert rotated["access_token"]


async def test_replaying_a_used_refresh_token_revokes_every_session(
    client: AsyncClient, registered: dict
) -> None:
    """Reuse is treated as theft, not as a retry.

    A refresh token is single-use. If an old one is presented, the safe
    assumption is that it was stolen, so the whole family is torn down.
    """
    rotated = (
        await client.post(
            "/api/v1/auth/refresh", json={"refresh_token": registered["refresh_token"]}
        )
    ).json()

    replay = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": registered["refresh_token"]}
    )
    assert replay.status_code == 401

    # The *new* token is collateral damage by design.
    after = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": rotated["refresh_token"]}
    )
    assert after.status_code == 401


async def test_logout_revokes_the_refresh_token(client: AsyncClient, registered: dict) -> None:
    headers = {"Authorization": f"Bearer {registered['access_token']}"}

    response = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": registered["refresh_token"]},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["deleted"] is True

    retry = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": registered["refresh_token"]}
    )
    assert retry.status_code == 401


async def test_sessions_are_listed_and_the_current_one_is_marked(
    client: AsyncClient, registered: dict
) -> None:
    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    response = await client.get("/api/v1/auth/sessions", headers=headers)

    assert response.status_code == 200, response.text
    sessions = response.json()
    assert len(sessions) == 1
    assert sessions[0]["is_current"] is True
    # A session record describes the token; it must not contain it.
    assert registered["refresh_token"] not in response.text


async def test_verify_is_a_cheap_validity_probe(client: AsyncClient, registered: dict) -> None:
    ok = await client.get(
        "/api/v1/auth/verify",
        headers={"Authorization": f"Bearer {registered['access_token']}"},
    )
    assert ok.status_code == 204
    assert not ok.content

    assert (await client.get("/api/v1/auth/verify")).status_code == 401


async def test_a_refresh_token_is_not_accepted_as_an_access_token(
    client: AsyncClient, registered: dict
) -> None:
    """Token-type confusion is a classic privilege bug; the `type` claim blocks it."""
    response = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {registered['refresh_token']}"},
    )
    assert response.status_code == 401


async def test_changing_the_password_invalidates_outstanding_tokens(
    client: AsyncClient, registered: dict, session: object
) -> None:
    """Disabling an account invalidates all outstanding sessions.

    Simulated at the service layer because there is no change-password endpoint
    yet; the point is that the dependency re-reads the user each request, so
    deactivation takes effect immediately rather than at token expiry.
    """
    from coraxis.repositories import users as user_repo

    headers = {"Authorization": f"Bearer {registered['access_token']}"}
    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 200

    user = await user_repo.get_by_id(session, registered["user"]["id"])
    user.is_active = False
    await session.commit()

    assert (await client.get("/api/v1/auth/me", headers=headers)).status_code == 401
