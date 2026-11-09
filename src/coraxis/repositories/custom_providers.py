"""Named custom OpenAI-compatible provider persistence.

This module is the only place that handles encrypted key material for custom
providers. Callers pass plaintext in and get it back only through
:func:`resolve_api_key`.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from coraxis.core.crypto import decrypt, encrypt, fingerprint
from coraxis.db.base import utcnow
from coraxis.db.models import CustomProvider


async def list_for_user(session: AsyncSession, user_id: str) -> list[CustomProvider]:
    result = await session.execute(
        select(CustomProvider)
        .where(CustomProvider.user_id == user_id)
        .order_by(CustomProvider.nickname)
    )
    return list(result.scalars().all())


async def get(session: AsyncSession, user_id: str, nickname: str) -> CustomProvider | None:
    result = await session.execute(
        select(CustomProvider).where(
            CustomProvider.user_id == user_id,
            CustomProvider.nickname == nickname,
        )
    )
    return result.scalar_one_or_none()


async def upsert(
    session: AsyncSession,
    user_id: str,
    nickname: str,
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    is_active: bool | None = None,
) -> CustomProvider:
    """Create or update a named custom provider.

    ``api_key=None`` leaves the stored key untouched — that is what lets the
    settings UI save a model or URL change without the browser re-sending the
    secret. Pass ``""`` to deliberately clear it.
    """
    provider = await get(session, user_id, nickname)

    if provider is None:
        provider = CustomProvider(
            user_id=user_id,
            nickname=nickname,
            base_url="",
            encrypted_key="",
        )
        session.add(provider)

    if base_url is not None:
        provider.base_url = base_url.strip()

    if model is not None:
        provider.model = model.strip()

    if api_key is not None:
        provider.encrypted_key = encrypt(api_key) if api_key else ""
        provider.key_hint = fingerprint(api_key) if api_key else ""
        provider.last_validated_at = None
        provider.last_validation_error = ""

    if is_active is not None:
        provider.is_active = is_active

    await session.flush()
    return provider


async def delete(session: AsyncSession, user_id: str, nickname: str) -> bool:
    provider = await get(session, user_id, nickname)
    if provider is None:
        return False
    await session.delete(provider)
    await session.flush()
    return True


async def mark_validated(session: AsyncSession, provider: CustomProvider, error: str = "") -> None:
    provider.last_validated_at = utcnow()
    provider.last_validation_error = error[:500]
    await session.flush()


def resolve_api_key(provider: CustomProvider | None) -> tuple[str, str]:
    """Return ``(api_key, source)`` for a custom provider.

    Precedence is user-stored key only (custom providers have no environment
    fallback). ``source`` is ``"user"`` or ``"none"``.
    """
    if provider is not None and provider.is_active and provider.encrypted_key:
        return decrypt(provider.encrypted_key), "user"
    return "", "none"
