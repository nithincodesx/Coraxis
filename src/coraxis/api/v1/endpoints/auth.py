"""Authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from coraxis.api.deps import CurrentUser, DbSession, TokenClaimsDep, client_metadata
from coraxis.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    SessionOut,
    TokenPair,
    UserOut,
)
from coraxis.schemas.common import DeletedResponse
from coraxis.services import auth as auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=TokenPair,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
)
async def register(payload: RegisterRequest, request: Request, session: DbSession) -> TokenPair:
    """Register and sign in.

    The first account created on an instance becomes its administrator.
    """
    user_agent, client_ip = client_metadata(request)
    tokens = await auth_service.register(
        session, payload, user_agent=user_agent, client_ip=client_ip
    )
    await session.commit()
    return tokens


@router.post("/login", response_model=TokenPair, summary="Sign in")
async def login(payload: LoginRequest, request: Request, session: DbSession) -> TokenPair:
    user = await auth_service.authenticate(session, payload)
    user_agent, client_ip = client_metadata(request)
    tokens = await auth_service.issue_tokens(
        session, user, user_agent=user_agent, client_ip=client_ip
    )
    await session.commit()
    return tokens


@router.post("/refresh", response_model=TokenPair, summary="Rotate tokens")
async def refresh(payload: RefreshRequest, request: Request, session: DbSession) -> TokenPair:
    """Exchange a refresh token for a new pair.

    Refresh tokens are single-use. Replaying a used token revokes every session
    for that user, on the assumption that it was stolen.
    """
    user_agent, client_ip = client_metadata(request)
    tokens = await auth_service.refresh_tokens(
        session, payload.refresh_token, user_agent=user_agent, client_ip=client_ip
    )
    # Committing is load-bearing here: the rotation must be durable, or the
    # consumed token becomes replayable again.
    await session.commit()
    return tokens


@router.post("/logout", response_model=DeletedResponse, summary="Sign out")
async def logout(payload: LogoutRequest, user: CurrentUser, session: DbSession) -> DeletedResponse:
    """Revoke the supplied refresh token, or every session when ``all_sessions`` is set."""
    revoked = await auth_service.logout(session, user, payload)
    await session.commit()
    return DeletedResponse(deleted=revoked > 0, id=str(revoked))


@router.get("/me", response_model=UserOut, summary="Current account")
async def me(user: CurrentUser) -> UserOut:
    return UserOut.model_validate(user)


@router.get("/sessions", response_model=list[SessionOut], summary="Active sessions")
async def sessions(
    user: CurrentUser, session: DbSession, claims: TokenClaimsDep
) -> list[SessionOut]:
    return await auth_service.list_sessions(session, user, current_session_id=claims.sid)


@router.get("/verify", summary="Verify a token", status_code=status.HTTP_204_NO_CONTENT)
async def verify(claims: TokenClaimsDep) -> Response:
    """Cheap validity probe for the frontend's session check."""
    return Response(status_code=status.HTTP_204_NO_CONTENT)
