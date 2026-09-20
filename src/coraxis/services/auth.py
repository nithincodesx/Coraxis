"""Authentication: registration, login, token rotation, and sessions."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from coraxis.core.config import get_settings
from coraxis.core.errors import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
)
from coraxis.core.logging import get_logger
from coraxis.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    password_needs_rehash,
    validate_password_strength,
    verify_password,
)
from coraxis.db.base import utcnow
from coraxis.db.models import User
from coraxis.repositories import users as user_repo
from coraxis.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RegisterRequest,
    SessionOut,
    TokenPair,
    UserOut,
)

logger = get_logger("auth")


async def register(
    session: AsyncSession,
    payload: RegisterRequest,
    *,
    user_agent: str = "",
    client_ip: str = "",
) -> TokenPair:
    """Create an account and log it straight in."""
    settings = get_settings()

    existing = await user_repo.count(session)
    is_first_user = existing == 0

    if not settings.allow_registration and not is_first_user:
        raise AuthorizationError(
            "Registration is closed on this instance.",
            code="registration_closed",
        )

    if await user_repo.get_by_email(session, payload.email) is not None:
        raise ConflictError("An account with that email already exists.")

    validate_password_strength(payload.password)

    user = await user_repo.create(
        session,
        email=payload.email,
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
        # The first account owns the instance; later accounts are ordinary.
        is_superuser=is_first_user,
    )

    logger.info("registered user %s (first_user=%s)", user.id, is_first_user)
    return await issue_tokens(session, user, user_agent=user_agent, client_ip=client_ip)


async def authenticate(session: AsyncSession, payload: LoginRequest) -> User:
    """Verify credentials.

    A wrong email and a wrong password produce the identical error, so the
    endpoint cannot be used to enumerate which accounts exist.
    """
    user = await user_repo.get_by_email(session, payload.email)
    if user is None:
        raise AuthenticationError("Incorrect email or password.")

    if not verify_password(payload.password, user.password_hash):
        raise AuthenticationError("Incorrect email or password.")

    if not user.is_active:
        raise AuthorizationError("This account is disabled.")

    # Opportunistically upgrade the stored hash if the policy tightened.
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(payload.password)
        logger.info("rehashed password for user %s", user.id)

    await user_repo.record_login(session, user)
    return user


async def issue_tokens(
    session: AsyncSession,
    user: User,
    *,
    user_agent: str = "",
    client_ip: str = "",
) -> TokenPair:
    """Mint an access/refresh pair and persist the refresh session."""
    # The refresh token's jti doubles as the session id, and is stamped into the
    # access token as `sid` so a request can identify its own session.
    refresh_token, refresh_expiry, jti = create_refresh_token(
        user.id, token_version=user.token_version
    )
    access_token, access_expiry = create_access_token(
        user.id, token_version=user.token_version, session_id=jti
    )

    await user_repo.create_refresh_token(
        session,
        user_id=user.id,
        jti=jti,
        expires_at=refresh_expiry.replace(tzinfo=None),
        user_agent=user_agent,
        client_ip=client_ip,
    )

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=access_expiry,
        expires_in=get_settings().access_token_minutes * 60,
        user=UserOut.model_validate(user),
    )


async def refresh_tokens(
    session: AsyncSession,
    refresh_token: str,
    *,
    user_agent: str = "",
    client_ip: str = "",
) -> TokenPair:
    """Rotate a refresh token.

    Refresh tokens are single-use. Presenting one that has already been rotated
    is the classic signature of a stolen token, so the response is to revoke
    every session that user holds rather than to hand out a new pair.
    """
    claims = decode_token(refresh_token, expected_type=TokenType.REFRESH)

    stored = await user_repo.get_refresh_token(session, claims.jti)
    if stored is None:
        raise AuthenticationError("This session is no longer valid. Sign in again.")

    if stored.is_revoked:
        revoked = await user_repo.revoke_all_refresh_tokens(session, stored.user_id)
        # Committing here is load-bearing, not a style choice. This function
        # raises on the next line, and the request-scoped session rolls back
        # when an exception propagates — which would silently undo the very
        # revocation that makes token theft survivable, leaving the attacker's
        # rotated token working. The theft response has to outlive the error.
        await session.commit()
        logger.warning(
            "refresh-token reuse detected for user %s; revoked %d session(s)",
            stored.user_id,
            revoked,
        )
        raise AuthenticationError(
            "This refresh token has already been used. All sessions were signed out "
            "as a precaution. Sign in again."
        )

    if stored.expires_at < utcnow():
        raise AuthenticationError("Your session has expired. Sign in again.")

    user = await user_repo.get_by_id(session, stored.user_id)
    if user is None or not user.is_active:
        raise AuthenticationError("This account is no longer active.")

    if claims.ver != user.token_version:
        raise AuthenticationError("Your session was invalidated. Sign in again.")

    await user_repo.revoke_refresh_token(session, stored)
    return await issue_tokens(session, user, user_agent=user_agent, client_ip=client_ip)


async def logout(session: AsyncSession, user: User, payload: LogoutRequest) -> int:
    """Revoke one session, or every session when ``all_sessions`` is set."""
    if payload.all_sessions:
        count = await user_repo.revoke_all_refresh_tokens(session, user.id)
        # Bumping the token version invalidates access tokens too.
        await user_repo.bump_token_version(session, user)
        return count

    if not payload.refresh_token:
        return 0

    try:
        claims = decode_token(payload.refresh_token, expected_type=TokenType.REFRESH)
    except AuthenticationError:
        # An unreadable token is already useless; treat logout as successful.
        return 0

    stored = await user_repo.get_refresh_token(session, claims.jti)
    if stored is None or stored.user_id != user.id:
        return 0

    await user_repo.revoke_refresh_token(session, stored)
    return 1


async def list_sessions(
    session: AsyncSession, user: User, *, current_session_id: str = ""
) -> list[SessionOut]:
    """Active sessions, newest first, flagging the caller's own.

    ``current_session_id`` is the ``sid`` claim from the caller's access token,
    which equals the ``jti`` of the refresh token issued with it.
    """
    rows = await user_repo.list_sessions(session, user.id)
    return [
        SessionOut(
            id=row.id,
            created_at=row.created_at,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            user_agent=row.user_agent,
            client_ip=row.client_ip,
            is_current=bool(current_session_id) and row.jti == current_session_id,
        )
        for row in rows
    ]
