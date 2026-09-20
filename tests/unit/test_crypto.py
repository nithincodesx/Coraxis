"""Unit tests for credential encryption and secret masking."""

from __future__ import annotations

import pytest

from coraxis.core.crypto import decrypt, encrypt, fingerprint, mask_secret


def test_round_trip() -> None:
    secret = "gsk_abcdefghijklmnopqrstuvwxyz0123456789"
    assert decrypt(encrypt(secret)) == secret


def test_ciphertext_differs_each_time() -> None:
    """Fernet includes a random IV, so identical inputs must not collide."""
    secret = "same-key-twice"
    assert encrypt(secret) != encrypt(secret)


def test_ciphertext_does_not_contain_plaintext() -> None:
    secret = "gsk_verydistinctivekeyvalue"
    assert secret not in encrypt(secret)


def test_empty_values_are_passthrough() -> None:
    assert encrypt("") == ""
    assert decrypt("") == ""


def test_decrypting_foreign_ciphertext_raises_actionable_error() -> None:
    """A key rotation must produce guidance, not a stack trace."""
    from coraxis.core.errors import ConfigurationError

    with pytest.raises(ConfigurationError, match="Re-enter the provider key"):
        decrypt("not-a-valid-fernet-token")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("", ""),
        ("abcd", "••••"),
        ("abcdefgh", "••••••••efgh"),
        ("sk-1234567890", "••••••••7890"),
    ],
)
def test_mask_secret_never_reveals_more_than_four_characters(value: str, expected: str) -> None:
    masked = mask_secret(value)
    assert masked == expected
    if len(value) > 4:
        # The bulk of the secret must be gone.
        assert value[:-4] not in masked


def test_fingerprint_returns_tail_only() -> None:
    assert fingerprint("sk-abcdefgh") == "efgh"
    assert fingerprint("abc") == "abc"
    assert fingerprint("") == ""
