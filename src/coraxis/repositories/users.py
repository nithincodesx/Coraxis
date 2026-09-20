"""User and session persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from coraxis.db.base import utcnow
from coraxis.db.models import RefreshToken, User
from coraxis.repositories._shared import affected_rows


def normalise_email(email: str) -> str:
    """Emails are compared case-insensitively; store the canonical form."""
    return email.strip().lower()


async def get_by_id(session: AsyncSession, user_id: str) -> User | None:
    return await session.get(User, user_id)


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == normalise_email(email)))
    return result.scalar_one_or_none()


async def create(
    session: AsyncSession,
    *,
    email: str,
    password_hash: str,
    display_name: str = "",
    is_superuser: bool = False,
) -> User:
    user = User(
        email=normalise_email(email),
        password_hash=password_hash,
        display_name=display_name.strip(),
        is_superuser=is_superuser,
    )
    session.add(user)
    await session.flush()
    return user


async def count(session: AsyncSession) -> int:
    """Total users. Used to decide whether the first account may self-promote."""
    result = await session.execute(select(func.count()).select_from(User))
    return int(result.scalar_one())


async def record_login(session: AsyncSession, user: User) -> None:
    user.last_login_at = utcnow()
    await session.flush()


async def set_password(session: AsyncSession, user: User, password_hash: str) -> None:
    """Change a password and invalidate every existing token for that user."""
    user.password_hash = password_hash
    user.token_version += 1
    await session.flush()


async def bump_token_version(session: AsyncSession, user: User) -> None:
    """Invalidate all outstanding tokens without touching the password."""
    user.token_version += 1
    await session.flush()


# ─── Refresh-token sessions ──────────────────────────────────────────


async def create_refresh_token(
    session: AsyncSession,
    *,
    user_id: str,
    jti: str,
    expires_at: datetime,
    user_agent: str = "",
    client_ip: str = "",
) -> RefreshToken:
    token = RefreshToken(
        user_id=user_id,
        jti=jti,
        expires_at=expires_at,
        user_agent=user_agent[:255],
        client_ip=client_ip[:64],
    )
    session.add(token)
    await session.flush()
    return token


async def get_refresh_token(session: AsyncSession, jti: str) -> RefreshToken | None:
    result = await session.execute(select(RefreshToken).where(RefreshToken.jti == jti))
    return result.scalar_one_or_none()


async def revoke_refresh_token(session: AsyncSession, token: RefreshToken) -> None:
    if token.revoked_at is None:
        token.revoked_at = utcnow()
        await session.flush()


async def revoke_all_refresh_tokens(session: AsyncSession, user_id: str) -> int:
    """Revoke every active session for a user. Returns the number revoked."""
    result = await session.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    return affected_rows(result)


async def list_sessions(
    session: AsyncSession, user_id: str, *, include_revoked: bool = False
) -> list[RefreshToken]:
    statement = select(RefreshToken).where(RefreshToken.user_id == user_id)
    if not include_revoked:
        statement = statement.where(RefreshToken.revoked_at.is_(None))
    statement = statement.order_by(RefreshToken.created_at.desc())
    result = await session.execute(statement)
    return list(result.scalars().all())


async def delete_expired_sessions(session: AsyncSession) -> int:
    """Housekeeping: drop sessions that expired or were revoked over a week ago."""
    from datetime import timedelta

    cutoff = utcnow() - timedelta(days=7)
    result = await session.execute(
        delete(RefreshToken).where(
            RefreshToken.expires_at < utcnow(),
            RefreshToken.created_at < cutoff,
        )
    )
    return affected_rows(result)
