"""FastAPI dependencies: authentication, pagination, and client metadata."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from coraxis.core.errors import AuthenticationError, AuthorizationError
from coraxis.core.logging import user_id_var
from coraxis.core.security import TokenClaims, TokenType, decode_token
from coraxis.db.models import User
from coraxis.db.session import get_db
from coraxis.repositories import users as user_repo

#: ``auto_error=False`` so a missing header produces our problem+json envelope
#: rather than Starlette's bare 403.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_token_claims(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> TokenClaims:
    """Decode and validate the bearer token."""
    if credentials is None or not credentials.credentials:
        raise AuthenticationError(
            "Provide a bearer access token in the Authorization header.",
            extra={"hint": "POST /api/v1/auth/login to obtain one."},
        )
    return decode_token(credentials.credentials, expected_type=TokenType.ACCESS)


TokenClaimsDep = Annotated[TokenClaims, Depends(get_token_claims)]


async def get_current_user(session: DbSession, claims: TokenClaimsDep) -> User:
    """Resolve the authenticated user.

    Re-reads the user on every request so that deactivation, deletion, and
    token-version bumps take effect immediately rather than at token expiry.
    """
    user = await user_repo.get_by_id(session, claims.sub)
    if user is None:
        raise AuthenticationError("This account no longer exists.")
    if not user.is_active:
        raise AuthorizationError("This account is disabled.")
    if claims.ver != user.token_version:
        raise AuthenticationError("Your session was invalidated. Sign in again.")

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
    "Pagination",
    "PaginationDep",
    "SuperUser",
    "TokenClaimsDep",
    "bearer_scheme",
    "client_metadata",
    "status",
]
