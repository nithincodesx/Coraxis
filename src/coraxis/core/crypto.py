"""Encryption for credentials at rest.

Provider API keys are the crown jewels of this application: a leaked Groq key
is someone else's bill. They are therefore never stored in plaintext.

The key is derived from ``CORAXIS_SECRET_KEY`` unless ``CORAXIS_ENCRYPTION_KEY``
is set explicitly, which lets you rotate the JWT signing key without making
stored credentials undecryptable.
"""

from __future__ import annotations

import base64
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from coraxis.core.config import get_settings
from coraxis.core.errors import ConfigurationError
from coraxis.core.logging import get_logger

logger = get_logger("crypto")

#: Changing this salt invalidates every previously stored credential.
_KDF_SALT = b"coraxis/credential-encryption/v1"
_KDF_INFO = b"fernet-key"


def _derive_key(secret: str) -> bytes:
    """Deterministically derive a Fernet key from an arbitrary secret."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_KDF_SALT,
        info=_KDF_INFO,
    )
    return base64.urlsafe_b64encode(hkdf.derive(secret.encode("utf-8")))


@lru_cache(maxsize=1)
def _fernet() -> Fernet:
    settings = get_settings()

    explicit = settings.encryption_key.get_secret_value().strip()
    if explicit:
        try:
            return Fernet(explicit.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise ConfigurationError(
                "CORAXIS_ENCRYPTION_KEY is not a valid Fernet key. Generate one with: "
                'python -c "from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            ) from exc

    secret = settings.secret_key.get_secret_value().strip()
    if not secret:
        # Development convenience: a stable per-installation key so credentials
        # survive a restart. Production startup already rejects an empty secret.
        logger.warning(
            "CORAXIS_SECRET_KEY is unset; deriving an insecure development key. "
            "Stored credentials will not be portable between machines."
        )
        secret = "coraxis-insecure-development-key"
    return Fernet(_derive_key(secret))


def encrypt(plaintext: str) -> str:
    """Encrypt a secret for storage. Returns an opaque URL-safe string."""
    if not plaintext:
        return ""
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt(ciphertext: str) -> str:
    """Decrypt a stored secret.

    Raises :class:`ConfigurationError` if the value cannot be decrypted — which
    almost always means ``CORAXIS_SECRET_KEY`` changed after the value was
    written.
    """
    if not ciphertext:
        return ""
    try:
        return _fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise ConfigurationError(
            "A stored credential could not be decrypted. This usually means "
            "CORAXIS_SECRET_KEY (or CORAXIS_ENCRYPTION_KEY) changed after the "
            "credential was saved. Re-enter the provider key in Settings."
        ) from exc


def mask_secret(value: str, *, visible: int = 4) -> str:
    """Return a display-safe rendering of a secret, e.g. ``••••••••4f2a``."""
    if not value:
        return ""
    if len(value) <= visible:
        return "•" * len(value)
    return "•" * 8 + value[-visible:]


def fingerprint(value: str, *, visible: int = 4) -> str:
    """Return the trailing characters of a secret, for display only."""
    if not value:
        return ""
    return value[-visible:] if len(value) > visible else value


def reset_crypto_cache() -> None:
    """Clear the cached Fernet instance. Intended for tests."""
    _fernet.cache_clear()
