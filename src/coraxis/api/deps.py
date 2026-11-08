"""FastAPI dependencies: authentication, pagination, and client metadata."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from coraxis.core.errors import AuthenticationError, AuthorizationError
from coraxis.core.firebase import FirebaseUser, get_or_create_user, verify_id_token
from coraxis.core.logging import user_id_var
from coraxis.db.models import User
from coraxis.db.session import get_db

#: ``auto_error=False`` so a missing header produces our problem+json envelope
#: rather than Starlette's bare 403.
bearer_scheme = HTTPBearer(auto_error=False, description="Firebase ID token")

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


async def get_current_user(session: DbSession, firebase_user: FirebaseUserDep) -> User:
    """Resolve the authenticated Coraxis user from a Firebase ID token.

    Re-reads the user on every request so that deactivation takes effect
    immediately. Creates a Coraxis account on first sign-in (the first account
    becomes the instance administrator).
    """
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
