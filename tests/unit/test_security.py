"""Unit tests for password hashing and JWT handling."""

from __future__ import annotations

import time

import jwt
import pytest

from coraxis.core.errors import AuthenticationError, ValidationError
from coraxis.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    new_jti,
    password_needs_rehash,
    validate_password_strength,
    verify_password,
)


def test_hash_is_salted_and_verifiable() -> None:
    password = "correct-horse-battery-staple"
    first = hash_password(password)
    second = hash_password(password)

    assert first != second, "identical passwords must not produce identical hashes"
    assert password not in first
    assert verify_password(password, first)
    assert verify_password(password, second)


def test_wrong_password_is_rejected() -> None:
    hashed = hash_password("the-right-one")
    assert not verify_password("the-wrong-one", hashed)


def test_corrupt_hash_returns_false_rather_than_raising() -> None:
    """A malformed stored hash must fail closed, not explode."""
    assert not verify_password("anything", "not-a-valid-argon2-hash")


def test_fresh_hash_does_not_need_rehash() -> None:
    assert not password_needs_rehash(hash_password("a-sufficiently-long-password"))


@pytest.mark.parametrize("password", ["short", "", "   ", "x" * 2000])
def test_weak_passwords_are_rejected(password: str) -> None:
    with pytest.raises(ValidationError):
        validate_password_strength(password)


def test_password_with_surrounding_whitespace_is_rejected() -> None:
    with pytest.raises(ValidationError, match="whitespace"):
        validate_password_strength(" leading-and-trailing ")


def test_access_token_round_trip() -> None:
    token, expiry = create_access_token("user-123")
    claims = decode_token(token, expected_type=TokenType.ACCESS)

    assert claims.sub == "user-123"
    assert claims.type is TokenType.ACCESS
    assert claims.exp > int(time.time())
    assert expiry.timestamp() == pytest.approx(claims.exp, abs=1)


def test_refresh_token_returns_its_jti_for_revocation() -> None:
    token, _expiry, jti = create_refresh_token("user-123")
    claims = decode_token(token, expected_type=TokenType.REFRESH)

    assert claims.jti == jti
    assert claims.type is TokenType.REFRESH


def test_token_type_confusion_is_rejected() -> None:
    """A refresh token must not be usable as an access token."""
    refresh, _expiry, _jti = create_refresh_token("user-123")

    with pytest.raises(AuthenticationError, match="Expected a access token"):
        decode_token(refresh, expected_type=TokenType.ACCESS)


def test_tampered_signature_is_rejected() -> None:
    token, _expiry = create_access_token("user-123")
    header, payload, signature = token.split(".")
    forged = f"{header}.{payload}.{signature[:-4]}AAAA"

    with pytest.raises(AuthenticationError, match="invalid"):
        decode_token(forged, expected_type=TokenType.ACCESS)


def test_expired_token_is_rejected() -> None:
    from coraxis.core.config import get_settings

    settings = get_settings()
    now = int(time.time())
    expired = jwt.encode(
        {
            "sub": "user-123",
            "type": "access",
            "jti": new_jti(),
            "iat": now - 7200,
            "exp": now - 3600,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
            "ver": 0,
        },
        settings.secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

    with pytest.raises(AuthenticationError, match="expired"):
        decode_token(expired, expected_type=TokenType.ACCESS)


def test_garbage_token_is_rejected() -> None:
    with pytest.raises(AuthenticationError):
        decode_token("clearly-not-a-jwt", expected_type=TokenType.ACCESS)


def test_jti_values_are_unique() -> None:
    assert len({new_jti() for _ in range(500)}) == 500
