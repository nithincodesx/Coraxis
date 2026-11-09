"""Password hashing and JWT issuance.

Passwords use Argon2id. Access tokens are short-lived JWTs; refresh tokens are
JWTs too, but their ``jti`` is persisted so a single session can be revoked
without invalidating every token the user holds.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from pydantic import BaseModel
from pydantic import ValidationError as PydanticValidationError

from coraxis.core.config import get_settings
from coraxis.core.errors import AuthenticationError, ValidationError
from coraxis.core.logging import get_logger

logger = get_logger("security")

#: Argon2id with the library's default parameters (3 iterations, 64 MiB,
#: 4 lanes). Deliberately not tuned down — password hashing is not on the
#: hot path.
_hasher = PasswordHasher()

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024  # Argon2 has no limit; this bounds request size abuse.


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


class TokenClaims(BaseModel):
    """Decoded and validated JWT payload."""

    sub: str
    type: TokenType
    jti: str
    iat: int
    exp: int
    iss: str
    aud: str
    ver: int = 0
    #: The refresh session this token belongs to. An access token carries the
    #: ``jti`` of the refresh token issued alongside it, so a request can say
    #: *which* session it is using. Without it there is no way to flag the
    #: caller's own session: access and refresh tokens have distinct ``jti``
    #: values by construction, so comparing them never matches.
    sid: str = ""


# ─── Passwords ───────────────────────────────────────────────────────


def validate_password_strength(password: str) -> None:
    """Reject obviously weak passwords before they are hashed."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at least {MIN_PASSWORD_LENGTH} characters.",
            extra={"field": "password"},
        )
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValidationError(
            f"Password must be at most {MAX_PASSWORD_LENGTH} characters.",
            extra={"field": "password"},
        )
    if password.strip() != password:
        raise ValidationError("Password must not begin or end with whitespace.")


def hash_password(password: str) -> str:
    """Hash a password with Argon2id."""
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password, returning ``False`` rather than raising on mismatch."""
    try:
        _hasher.verify(hashed, password)
        return True
    except VerifyMismatchError:
        return False
    except (VerificationError, InvalidHashError):
        # A corrupt or foreign hash must not be treated as a successful match.
        logger.warning("password verification failed due to an invalid stored hash")
        return False


def password_needs_rehash(hashed: str) -> bool:
    """True when the stored hash used weaker parameters than the current policy."""
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


# ─── Tokens ──────────────────────────────────────────────────────────


def new_jti() -> str:
    """Generate a unique token identifier."""
    return secrets.token_urlsafe(24)


def _encode(claims: dict[str, Any], expires: timedelta) -> tuple[str, datetime]:
    settings = get_settings()
    now = datetime.now(UTC)
    expiry = now + expires

    payload = {
        **claims,
        "iat": int(now.timestamp()),
        "exp": int(expiry.timestamp()),
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
    }

    token = jwt.encode(
        payload,
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, expiry


def create_access_token(
    user_id: str, *, token_version: int = 0, session_id: str = ""
) -> tuple[str, datetime]:
    """Issue a short-lived access token. Returns ``(token, expires_at)``.

    ``session_id`` should be the ``jti`` of the refresh token issued with it,
    which lets the sessions endpoint identify the caller's own session.
    """
    settings = get_settings()
    payload: dict[str, object] = {
        "sub": user_id,
        "type": TokenType.ACCESS.value,
        "jti": new_jti(),
        "ver": token_version,
    }
    if session_id:
        payload["sid"] = session_id
    return _encode(payload, timedelta(minutes=settings.access_token_minutes))


def create_refresh_token(
    user_id: str, *, token_version: int = 0, jti: str | None = None
) -> tuple[str, datetime, str]:
    """Issue a refresh token.

    Returns ``(token, expires_at, jti)``. The caller must persist ``jti`` so the
    session can later be revoked.
    """
    settings = get_settings()
    identifier = jti or new_jti()
    token, expiry = _encode(
        {
            "sub": user_id,
            "type": TokenType.REFRESH.value,
            "jti": identifier,
            "ver": token_version,
        },
        timedelta(days=settings.refresh_token_days),
    )
    return token, expiry, identifier


def decode_token(token: str, *, expected_type: TokenType) -> TokenClaims:
    """Decode and validate a JWT.

    Raises :class:`AuthenticationError` for every failure mode so callers get a
    single, uniform 401 and attackers learn nothing from the distinction.
    """
    settings = get_settings()

    try:
        raw = jwt.decode(
            token,
            settings.secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
            issuer=settings.jwt_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Token is invalid.") from exc

    try:
        claims = TokenClaims.model_validate(raw)
    except PydanticValidationError as exc:
        raise AuthenticationError("Token payload is malformed.") from exc

    if claims.type is not expected_type:
        raise AuthenticationError(
            f"Expected a {expected_type.value} token but received a {claims.type.value} token."
        )

    return claims
