"""Authentication and account schemas."""

from __future__ import annotations

from pydantic import EmailStr, Field, field_validator

from coraxis.core.security import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from coraxis.schemas.common import RequestModel, ResponseModel, UTCDatetime


class RegisterRequest(RequestModel):
    email: EmailStr
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=MAX_PASSWORD_LENGTH)
    display_name: str = Field(default="", max_length=120)

    @field_validator("password")
    @classmethod
    def _no_surrounding_whitespace(cls, value: str) -> str:
        if value.strip() != value:
            raise ValueError("Password must not begin or end with whitespace.")
        return value


class LoginRequest(RequestModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=MAX_PASSWORD_LENGTH)


class RefreshRequest(RequestModel):
    """Exchange a refresh token for a new pair.

    A plain body field rather than a cookie: the API is consumed by a separate
    origin (the Next.js app), where cross-site cookies bring CSRF obligations
    that a bearer token avoids.
    """

    refresh_token: str = Field(min_length=1)


class LogoutRequest(RequestModel):
    refresh_token: str = Field(default="")
    all_sessions: bool = False


class UserOut(ResponseModel):
    """A user as exposed over the API. Never includes the password hash."""

    id: str
    email: EmailStr
    display_name: str
    is_active: bool
    is_superuser: bool
    created_at: UTCDatetime
    last_login_at: UTCDatetime | None = None


class TokenPair(ResponseModel):
    """The result of a successful login or refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_at: UTCDatetime
    expires_in: int = Field(description="Access-token lifetime in seconds.")
    user: UserOut


class SessionOut(ResponseModel):
    """An active refresh-token session, for the account settings screen."""

    id: str
    created_at: UTCDatetime
    expires_at: UTCDatetime
    revoked_at: UTCDatetime | None = None
    user_agent: str = ""
    client_ip: str = ""
    is_current: bool = False
