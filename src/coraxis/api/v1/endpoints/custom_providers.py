"""Named custom OpenAI-compatible provider endpoints.

A key goes in, and it never comes back out. Responses carry only a four-character
hint so the settings screen can distinguish between providers.
"""

from __future__ import annotations

from fastapi import APIRouter, status

from coraxis.api.deps import CurrentUser, DbSession
from coraxis.core.errors import NotFoundError, ValidationError
from coraxis.repositories import custom_providers as provider_repo
from coraxis.schemas.common import DeletedResponse
from coraxis.schemas.credentials import (
    CustomProviderOut,
    CustomProviderTestRequest,
    CustomProviderTestResult,
    CustomProviderUpsert,
)
from coraxis.services.llm import validate_provider_key

router = APIRouter(prefix="/custom-providers", tags=["custom-providers"])


def _to_out(provider) -> CustomProviderOut:
    """Serialise a custom provider without its encrypted payload."""
    return CustomProviderOut(
        id=provider.id,
        nickname=provider.nickname,
        base_url=provider.base_url,
        model=provider.model,
        key_hint=provider.key_hint,
        is_active=provider.is_active,
        has_key=bool(provider.encrypted_key),
        last_validated_at=provider.last_validated_at,
        last_validation_error=provider.last_validation_error,
        created_at=provider.created_at,
        updated_at=provider.updated_at,
    )


@router.get(
    "",
    response_model=list[CustomProviderOut],
    summary="List stored custom providers",
)
async def list_custom_providers(user: CurrentUser, session: DbSession) -> list[CustomProviderOut]:
    rows = await provider_repo.list_for_user(session, user.id)
    return [_to_out(row) for row in rows]


@router.put(
    "",
    response_model=CustomProviderOut,
    summary="Store or replace a named custom provider",
)
async def upsert_custom_provider(
    payload: CustomProviderUpsert, user: CurrentUser, session: DbSession
) -> CustomProviderOut:
    """Save a named OpenAI-compatible endpoint.

    Omit ``api_key`` to change the URL or model without re-sending the secret.
    """
    existing = await provider_repo.get(session, user.id, payload.nickname)
    if existing is None and not payload.base_url.strip():
        # Creating: require a base URL.
        raise ValidationError(
            "A custom provider needs a base URL, for example https://api.inceptionlabs.ai/v1"
        )

    # On update, an omitted base URL leaves the stored value untouched.
    base_url = payload.base_url or None

    provider = await provider_repo.upsert(
        session,
        user.id,
        payload.nickname,
        base_url=base_url,
        model=payload.model,
        api_key=payload.api_key if payload.api_key else None,
    )
    await session.commit()
    return _to_out(provider)


@router.delete(
    "/{nickname}",
    response_model=DeletedResponse,
    summary="Delete a named custom provider",
)
async def delete_custom_provider(
    nickname: str, user: CurrentUser, session: DbSession
) -> DeletedResponse:
    deleted = await provider_repo.delete(session, user.id, nickname)
    if not deleted:
        raise NotFoundError(f"No custom provider named '{nickname}' is stored.")
    await session.commit()
    return DeletedResponse(deleted=True, id=nickname)


@router.post(
    "/test",
    response_model=CustomProviderTestResult,
    summary="Validate a custom provider key without storing it",
)
async def test_custom_provider(
    payload: CustomProviderTestRequest,
) -> CustomProviderTestResult:
    """Make one minimal call to confirm a custom provider works.

    Deliberately does not require the provider to be stored first.
    """
    if not payload.base_url.strip():
        return CustomProviderTestResult(
            valid=False,
            nickname=payload.nickname,
            model=payload.model,
            error="A custom provider needs a base URL.",
            latency_ms=0,
        )

    result = await validate_provider_key(
        "custom",
        payload.api_key,
        payload.model,
        base_url=payload.base_url,
    )
    return CustomProviderTestResult(
        valid=result.valid,
        nickname=payload.nickname,
        model=result.model,
        error=result.error,
        latency_ms=result.latency_ms,
    )


@router.post(
    "/{nickname}/validate",
    response_model=CustomProviderOut,
    summary="Re-validate a stored custom provider",
    status_code=status.HTTP_200_OK,
)
async def validate_stored_custom_provider(
    nickname: str, user: CurrentUser, session: DbSession
) -> CustomProviderOut:
    """Check a stored custom provider key and record the verdict against it."""
    provider = await provider_repo.get(session, user.id, nickname)
    if provider is None:
        raise NotFoundError(f"No custom provider named '{nickname}' is stored.")

    api_key, _ = provider_repo.resolve_api_key(provider)
    result = await validate_provider_key(
        "custom",
        api_key,
        provider.model,
        base_url=provider.base_url,
    )
    await provider_repo.mark_validated(session, provider, "" if result.valid else result.error)
    await session.commit()
    return _to_out(provider)
