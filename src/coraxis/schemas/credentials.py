"""Provider credential schemas.

The governing rule for this module: a plaintext API key may travel *in* but
never *out*. :class:`CredentialOut` has no field that could carry one, so an
endpoint cannot leak a secret even by accident.
"""

from __future__ import annotations

from pydantic import Field, field_validator

from coraxis.db.enums import ProviderName
from coraxis.schemas.common import RequestModel, ResponseModel, UTCDatetime


class CredentialUpsert(RequestModel):
    """Create or replace a stored provider key."""

    provider: ProviderName
    api_key: str = Field(default="", max_length=1024)
    base_url: str = Field(default="", max_length=255)
    #: Pin the model for this provider. Empty keeps the built-in default.
    default_model: str = Field(default="", max_length=160)

    @field_validator("api_key")
    @classmethod
    def _reject_placeholder(cls, value: str) -> str:
        """Catch the two mistakes people actually make when pasting keys."""
        if value and value.strip() != value:
            raise ValueError("API key must not contain leading or trailing whitespace.")
        if value.lower() in {"your-key-here", "sk-...", "changeme", "todo"}:
            raise ValueError("That looks like a placeholder, not an API key.")
        return value


class CredentialOut(ResponseModel):
    """A stored credential, described but never disclosed.

    ``key_hint`` is the last four characters, which is enough to tell two keys
    apart in a settings screen and useless to anyone else.
    """

    id: str
    provider: ProviderName
    key_hint: str = ""
    base_url: str = ""
    default_model: str = ""
    is_active: bool
    has_key: bool = False
    last_validated_at: UTCDatetime | None = None
    last_validation_error: str = ""
    created_at: UTCDatetime
    updated_at: UTCDatetime


class CredentialTestRequest(RequestModel):
    """Validate a key without storing it."""

    provider: ProviderName
    api_key: str = Field(default="", max_length=1024)
    model: str = Field(default="", max_length=160)
    base_url: str = Field(default="", max_length=255)


class CredentialTestResult(ResponseModel):
    valid: bool
    provider: ProviderName
    model: str = ""
    error: str = ""
    latency_ms: int = 0


class ModelListRequest(RequestModel):
    """Ask a provider what models it currently serves.

    ``api_key`` may be empty when one is already stored, so the catalogue can be
    refreshed without re-pasting a secret the browser does not hold.
    """

    provider: ProviderName
    api_key: str = Field(default="", max_length=1024)
    base_url: str = Field(default="", max_length=255)


class ModelListResult(ResponseModel):
    models: list[str] = Field(default_factory=list)
    error: str = ""
    #: True when the ids came from the live provider rather than a fallback.
    live: bool = True


class ProviderStatus(ResponseModel):
    """What the UI needs to render the provider picker."""

    provider: ProviderName
    configured: bool
    source: str = Field(
        default="none",
        description="Where the active key came from: 'user', 'environment' or 'none'.",
    )
    key_hint: str = ""
    default_model: str = ""
    requires_key: bool = True
    #: A user-supplied base URL is mandatory for this provider.
    requires_base_url: bool = False
    #: The user's pinned model, if any. Empty means the default above applies.
    selected_model: str = ""
