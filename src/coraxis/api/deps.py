"""FastAPI dependencies: authentication, pagination, and client metadata."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from coraxis.core.errors import AuthenticationError, AuthorizationError
from coraxis.core.firebase import FirebaseUser, get_or_create_user, verify_id_token
from coraxis.core.logging import user_id_var
from coraxis.core.security import TokenType, decode_token
from coraxis.db.models import User
from coraxis.db.session import get_db
from coraxis.repositories import users as user_repo

#: ``auto_error=False`` so a missing header produces our problem+json envelope
#: rather than Starlette's bare 403.
bearer_scheme = HTTPBearer(
    auto_error=False, description="Firebase ID token or Coraxis access token"
)

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_firebase_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> FirebaseUser:
    """Verify the bearer Firebase ID token and return its trusted claims."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError(
            "Provide a bearer Firebase ID token in the Authorization header.",
            extra={"hint": "Sign in with GitHub or email on the frontend."},
        )
    return verify_id_token(credentials.credentials)


FirebaseUserDep = Annotated[FirebaseUser, Depends(get_firebase_user)]


async def _user_from_coraxis_token(session: AsyncSession, token: str) -> User | None:
    """Resolve a user from a Coraxis-issued access token, or ``None``.

    The local auth endpoints (``/auth/register``, ``/auth/login``,
    ``/auth/refresh``) issue JWT access tokens signed with
    ``CORAXIS_SECRET_KEY``. Those tokens must be accepted here — before this
    fallback existed they were issued successfully and then rejected by every
    protected route, because only Firebase ID tokens were verified.
    """
    try:
        claims = decode_token(token, expected_type=TokenType.ACCESS)
    except AuthenticationError:
        return None

    user = await user_repo.get_by_id(session, claims.sub)
    if user is None or claims.ver != user.token_version:
        return None
    return user


async def get_current_user(
    session: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> User:
    """Resolve the authenticated Coraxis user from the bearer token.

    Two token kinds are accepted:

    * a **Firebase ID token** (the frontend's sign-in flow) — verified via
      Firebase and mapped to a Coraxis account, created on first sign-in
      (the first account becomes the instance administrator);
    * a **Coraxis access token** issued by the local ``/auth/*`` endpoints —
      verified against ``CORAXIS_SECRET_KEY`` and its ``token_version``.

    Re-reads the user on every request so that deactivation takes effect
    immediately.
    """
    if credentials is None or not credentials.credentials:
        raise AuthenticationError(
            "Provide a bearer token in the Authorization header.",
            extra={"hint": "Sign in with GitHub or email on the frontend."},
        )

    token = credentials.credentials
    firebase_user: FirebaseUser | None = None
    firebase_error: AuthenticationError | None = None
    try:
        firebase_user = verify_id_token(token)
    except AuthenticationError as exc:
        firebase_error = exc

    if firebase_user is None:
        # Not a (valid) Firebase token — try a Coraxis-issued access token
        # before giving up, and surface the Firebase error if neither works.
        user = await _user_from_coraxis_token(session, token)
        if user is None:
            raise firebase_error  # type: ignore[misc]
        if not user.is_active:
            raise AuthorizationError("This account is disabled.")
        user_id_var.set(user.id)
        return user

    user = await get_or_create_user(session, firebase_user)
    if not user.is_active:
        raise AuthorizationError("This account is disabled.")

    user_id_var.set(user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_superuser(user: CurrentUser) -> User:
    if not user.is_superuser:
        raise AuthorizationError("This action requires an administrator account.")
    return user


SuperUser = Annotated[User, Depends(get_superuser)]


class Pagination:
    """Standard ``limit``/``offset`` query parameters."""

    def __init__(
        self,
        limit: Annotated[int, Query(ge=1, le=100, description="Page size.")] = 25,
        offset: Annotated[int, Query(ge=0, description="Records to skip.")] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


PaginationDep = Annotated[Pagination, Depends(Pagination)]


def client_metadata(request: Request) -> tuple[str, str]:
    """Return ``(user_agent, client_ip)`` for session records.

    ``X-Forwarded-For`` is honoured only for the first hop because that is the
    value a trusted reverse proxy sets; behind a proxy that does not strip the
    header, this is spoofable, which is why it is used for display only.
    """
    user_agent = request.headers.get("user-agent", "")[:255]
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else ""
    return user_agent, client_ip[:64]


__all__ = [
    "AuthenticationError",
    "CurrentUser",
    "DbSession",
    "FirebaseUser",
    "FirebaseUserDep",
    "Pagination",
    "PaginationDep",
    "SuperUser",
    "bearer_scheme",
    "client_metadata",
    "get_current_user",
    "get_firebase_user",
    "get_superuser",
    "status",
]
