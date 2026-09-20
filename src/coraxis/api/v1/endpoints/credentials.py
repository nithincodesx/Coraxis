"""Provider credential endpoints.

The governing rule: a key goes in, and it never comes back out. Responses carry
only a four-character hint so the settings screen can distinguish between keys.
"""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, status

from coraxis.api.deps import CurrentUser, DbSession
from coraxis.core.errors import NotFoundError, ValidationError
from coraxis.db.enums import (
    DEFAULT_MODELS,
    KEYLESS_PROVIDERS,
    PROVIDERS,
    REQUIRES_BASE_URL,
    ProviderName,
)
from coraxis.repositories import credentials as credential_repo
from coraxis.schemas.common import DeletedResponse
from coraxis.schemas.credentials import (
    CredentialOut,
    CredentialTestRequest,
    CredentialTestResult,
    CredentialUpsert,
    ModelListRequest,
    ModelListResult,
    ProviderStatus,
)
from coraxis.services.llm import list_provider_models, validate_provider_key

router = APIRouter(prefix="/credentials", tags=["credentials"])


def _as_provider(value: str) -> ProviderName | None:
    """Narrow a path segment to a known provider.

    ``ProviderName`` is a ``Literal`` and ``PROVIDERS`` is a plain
    ``tuple[str, ...]``, so membership does not narrow a ``str`` for the type
    checker. The cast is safe because the membership test is the proof, and it
    lives here rather than at each call site.
    """
    return cast("ProviderName", value) if value in PROVIDERS else None


def _to_out(credential) -> CredentialOut:
    """Serialise a credential without its encrypted payload."""
    return CredentialOut(
        id=credential.id,
        provider=credential.provider,
        key_hint=credential.key_hint,
        base_url=credential.base_url,
        default_model=credential.default_model,
        is_active=credential.is_active,
        has_key=bool(credential.encrypted_key),
        last_validated_at=credential.last_validated_at,
        last_validation_error=credential.last_validation_error,
        created_at=credential.created_at,
        updated_at=credential.updated_at,
    )


@router.get("", response_model=list[CredentialOut], summary="List stored credentials")
async def list_credentials(user: CurrentUser, session: DbSession) -> list[CredentialOut]:
    rows = await credential_repo.list_for_user(session, user.id)
    return [_to_out(row) for row in rows]


@router.get("/providers", response_model=list[ProviderStatus], summary="Provider availability")
async def provider_status(user: CurrentUser, session: DbSession) -> list[ProviderStatus]:
    """Which providers are ready to use, and where the active key comes from.

    This is what the frontend uses to decide whether to send a user to Settings
    before letting them start a run.
    """
    stored = {row.provider: row for row in await credential_repo.list_for_user(session, user.id)}

    statuses: list[ProviderStatus] = []
    for provider in PROVIDERS:
        credential = stored.get(provider)
        _, source = credential_repo.resolve_api_key(credential, provider)
        statuses.append(
            ProviderStatus(
                provider=provider,  # type: ignore[arg-type]
                configured=source != "none",
                source=source,
                key_hint=credential.key_hint if credential else "",
                default_model=DEFAULT_MODELS.get(provider, ""),
                requires_key=provider not in KEYLESS_PROVIDERS,
                requires_base_url=provider in REQUIRES_BASE_URL,
                selected_model=credential.default_model if credential else "",
            )
        )
    return statuses


@router.put("", response_model=CredentialOut, summary="Store or replace a credential")
async def upsert_credential(
    payload: CredentialUpsert, user: CurrentUser, session: DbSession
) -> CredentialOut:
    """Save a provider key.

    Omit ``api_key`` to change the model or base URL without re-sending the
    secret — the browser never has to hold it after the first save.
    """
    if payload.provider in REQUIRES_BASE_URL and not payload.base_url.strip():
        raise ValidationError(
            "This provider needs a base URL, for example https://api.inceptionlabs.ai/v1"
        )

    credential = await credential_repo.upsert(
        session,
        user.id,
        payload.provider,
        api_key=payload.api_key if payload.api_key else None,
        base_url=payload.base_url,
        default_model=payload.default_model,
    )
    await session.commit()
    return _to_out(credential)


@router.delete("/{provider}", response_model=DeletedResponse, summary="Delete a credential")
async def delete_credential(
    provider: str, user: CurrentUser, session: DbSession
) -> DeletedResponse:
    resolved = _as_provider(provider)
    if resolved is None:
        raise NotFoundError(f"Unknown provider: {provider}")

    deleted = await credential_repo.delete(session, user.id, resolved)
    if not deleted:
        raise NotFoundError("No credential stored for that provider.")
    await session.commit()
    return DeletedResponse(deleted=True, id=provider)


@router.post(
    "/test",
    response_model=CredentialTestResult,
    summary="Validate a key without storing it",
)
async def test_credential(payload: CredentialTestRequest) -> CredentialTestResult:
    """Make one minimal call to confirm a key works.

    Deliberately does not require the key to be stored first, so the settings
    screen can validate before saving.
    """
    result = await validate_provider_key(
        payload.provider,
        payload.api_key,
        payload.model,
        base_url=payload.base_url,
    )
    return CredentialTestResult(
        valid=result.valid,
        provider=payload.provider,
        model=result.model,
        error=result.error,
        latency_ms=result.latency_ms,
    )


@router.post(
    "/models",
    response_model=ModelListResult,
    summary="List the models a provider currently serves",
)
async def list_models(
    payload: ModelListRequest, user: CurrentUser, session: DbSession
) -> ModelListResult:
    """Ask the provider what it serves right now.

    A stored key is used when the request omits one, so the catalogue can be
    refreshed without the browser holding the secret. This is what keeps the
    model picker honest — providers retire ids constantly, and a hardcoded
    default only fails at run time with an opaque error.
    """
    api_key = payload.api_key
    base_url = payload.base_url

    if not api_key or not base_url:
        stored = await credential_repo.get(session, user.id, payload.provider)
        if stored is not None:
            if not api_key:
                api_key, _ = credential_repo.resolve_api_key(stored, payload.provider)
            if not base_url:
                base_url = stored.base_url

    models, error = await list_provider_models(payload.provider, api_key, base_url)
    return ModelListResult(models=models, error=error, live=not error)


@router.post(
    "/{provider}/validate",
    response_model=CredentialOut,
    summary="Re-validate a stored credential",
    status_code=status.HTTP_200_OK,
)
async def validate_stored(provider: str, user: CurrentUser, session: DbSession) -> CredentialOut:
    """Check a stored key and record the verdict against it."""
    resolved = _as_provider(provider)
    if resolved is None:
        raise NotFoundError(f"Unknown provider: {provider}")

    credential = await credential_repo.get(session, user.id, resolved)
    if credential is None:
        raise NotFoundError("No credential stored for that provider.")

    api_key, _ = credential_repo.resolve_api_key(credential, resolved)
    # The model must be passed as the model. This previously passed base_url in
    # that position, so every re-validation tested a nonsense model id and the
    # stored key looked broken.
    result = await validate_provider_key(
        resolved,
        api_key,
        credential.default_model,
        base_url=credential.base_url,
    )
    await credential_repo.mark_validated(session, credential, "" if result.valid else result.error)
    await session.commit()
    return _to_out(credential)
