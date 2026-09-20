"""Provider credential persistence.

This module is the only place that handles encrypted key material. Callers pass
plaintext in and get it back only through :func:`resolve_api_key`, which exists
so that exactly one function is responsible for decryption.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from coraxis.core.config import get_settings
from coraxis.core.crypto import decrypt, encrypt, fingerprint
from coraxis.db.base import utcnow
from coraxis.db.models import ProviderCredential


async def list_for_user(session: AsyncSession, user_id: str) -> list[ProviderCredential]:
    result = await session.execute(
        select(ProviderCredential)
        .where(ProviderCredential.user_id == user_id)
        .order_by(ProviderCredential.provider)
    )
    return list(result.scalars().all())


async def get(session: AsyncSession, user_id: str, provider: str) -> ProviderCredential | None:
    result = await session.execute(
        select(ProviderCredential).where(
            ProviderCredential.user_id == user_id,
            ProviderCredential.provider == provider,
        )
    )
    return result.scalar_one_or_none()


async def upsert(
    session: AsyncSession,
    user_id: str,
    provider: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    default_model: str | None = None,
    is_active: bool | None = None,
) -> ProviderCredential:
    """Create or update a credential.

    ``api_key=None`` leaves the stored key untouched — that is what lets the
    settings UI save a model change without the browser ever re-sending the
    secret. Pass ``""`` to deliberately clear it.
    """
    credential = await get(session, user_id, provider)

    if credential is None:
        credential = ProviderCredential(user_id=user_id, provider=provider, encrypted_key="")
        session.add(credential)

    if api_key is not None:
        credential.encrypted_key = encrypt(api_key) if api_key else ""
        credential.key_hint = fingerprint(api_key) if api_key else ""
        # A new key has not been proven yet; clear any stale verdict.
        credential.last_validated_at = None
        credential.last_validation_error = ""

    if base_url is not None:
        credential.base_url = base_url.strip()

    if default_model is not None:
        credential.default_model = default_model.strip()

    if is_active is not None:
        credential.is_active = is_active

    await session.flush()
    return credential


async def delete(session: AsyncSession, user_id: str, provider: str) -> bool:
    credential = await get(session, user_id, provider)
    if credential is None:
        return False
    await session.delete(credential)
    await session.flush()
    return True


async def mark_validated(
    session: AsyncSession, credential: ProviderCredential, error: str = ""
) -> None:
    credential.last_validated_at = utcnow()
    credential.last_validation_error = error[:500]
    await session.flush()


def resolve_api_key(credential: ProviderCredential | None, provider: str) -> tuple[str, str]:
    """Return ``(api_key, source)`` for a provider.

    Precedence is user-stored key, then environment fallback. ``source`` is
    ``"user"``, ``"environment"`` or ``"none"`` so callers can tell the user
    *where* their key is coming from when something fails.
    """
    if credential is not None and credential.is_active and credential.encrypted_key:
        return decrypt(credential.encrypted_key), "user"

    fallback = get_settings().providers.key_for(provider)
    if fallback:
        return fallback, "environment"

    return "", "none"
