"""LLM construction and provider validation.

Nothing above this module knows how a model string is formatted or which
provider needs a key. Callers resolve a config and ask for a client.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from crewai import LLM

from coraxis.core.errors import ConfigurationError, UpstreamError
from coraxis.core.logging import get_logger
from coraxis.db.enums import DEFAULT_MODELS, KEYLESS_PROVIDERS, ProviderName
from coraxis.services.llm.sanitizer import apply_litellm_patches

logger = get_logger("llm")

#: Provider prefixes understood by LiteLLM.
#:
#: ``custom`` maps to ``openai/`` because that is how LiteLLM is told "use the
#: OpenAI wire format against the base URL I give you" — which is exactly what
#: an OpenAI-compatible platform is.
_PROVIDER_PREFIX = {
    "groq": "groq",
    "gemini": "gemini",
    "openai": "openai",
    "ollama": "ollama",
    "custom": "openai",
}

_DEFAULT_OLLAMA_URL = "http://localhost:11434"


@dataclass(frozen=True, slots=True)
class LLMConfig:
    """A fully resolved LLM configuration, ready to build.

    ``api_key`` is excluded from ``repr`` so a stray ``logger.debug(config)``
    cannot write a credential to the logs.
    """

    agent_slug: str
    provider: ProviderName
    model: str
    api_key: str = field(default="", repr=False)
    base_url: str = ""
    temperature: float = 0.2
    max_tokens: int = 4096
    key_source: str = "none"

    @property
    def requires_key(self) -> bool:
        return self.provider not in KEYLESS_PROVIDERS

    def describe(self) -> dict[str, Any]:
        """A log-safe summary. Contains no key material."""
        return {
            "agent": self.agent_slug,
            "provider": self.provider,
            "model": self.model,
            "key_source": self.key_source,
            "temperature": self.temperature,
        }


@dataclass(frozen=True, slots=True)
class ValidationResult:
    """Outcome of a provider credential check."""

    valid: bool
    provider: str
    model: str
    error: str = ""
    latency_ms: int = 0


def format_model_string(provider: str, model: str) -> str:
    """Ensure a model id carries the provider prefix LiteLLM expects.

    ``llama-3.1-8b-instant`` becomes ``groq/llama-3.1-8b-instant``. Already
    prefixed ids are left alone, so a user pasting a fully qualified id from
    provider documentation is not double-prefixed.
    """
    model = (model or "").strip()
    prefix = _PROVIDER_PREFIX.get(provider, provider)
    if model.startswith(f"{prefix}/"):
        return model
    return f"{prefix}/{model}"


def resolve_model(provider: str, model: str) -> str:
    """Fall back to the provider's default when no model is configured."""
    return (model or "").strip() or DEFAULT_MODELS.get(provider, "")


def build_llm(config: LLMConfig) -> LLM:
    """Construct a CrewAI LLM from a resolved config.

    Raises :class:`ConfigurationError` when a key is required and absent —
    which is a user-fixable problem, so it is reported as a 400 rather than a
    500 with a stack trace.
    """
    apply_litellm_patches()

    if config.requires_key and not config.api_key:
        raise ConfigurationError(
            f"{config.provider} requires an API key, but none is configured for "
            f"agent '{config.agent_slug}'. Add one in Settings, or set the "
            f"{_env_var_for(config.provider)} environment variable."
        )

    model = format_model_string(config.provider, resolve_model(config.provider, config.model))

    if config.provider == "ollama":
        return LLM(
            model=model,
            base_url=config.base_url or _DEFAULT_OLLAMA_URL,
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            drop_params=True,
        )

    if config.provider == "custom":
        if not config.base_url.strip():
            raise ConfigurationError(
                "A custom OpenAI-compatible provider needs a base URL. Set one in "
                "Settings — for example https://api.inceptionlabs.ai/v1"
            )
        return LLM(
            model=model,
            api_key=config.api_key,
            base_url=config.base_url.strip(),
            temperature=config.temperature,
            max_tokens=config.max_tokens,
            drop_params=True,
        )

    return LLM(
        model=model,
        api_key=config.api_key,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        drop_params=True,
    )


async def validate_provider_key(
    provider: ProviderName,
    api_key: str,
    model: str = "",
    *,
    base_url: str = "",
) -> ValidationResult:
    """Make one minimal call to confirm a credential works.

    A single token is requested: enough to prove authentication and model
    access, cheap enough to be safe on a free tier.
    """
    apply_litellm_patches()

    if provider not in KEYLESS_PROVIDERS and not api_key.strip():
        return ValidationResult(False, provider, model, "No API key was provided.")

    resolved_model = format_model_string(provider, resolve_model(provider, model))
    started = time.perf_counter()

    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
        "drop_params": True,
    }
    if provider == "ollama":
        kwargs["base_url"] = base_url or _DEFAULT_OLLAMA_URL
    elif provider == "custom":
        if not base_url.strip():
            return ValidationResult(
                False, provider, model, "A custom provider needs a base URL.", 0
            )
        kwargs["api_key"] = api_key
        kwargs["base_url"] = base_url.strip()
    else:
        kwargs["api_key"] = api_key

    try:
        import litellm

        await litellm.acompletion(**kwargs)
    except Exception as exc:  # noqa: BLE001 - every failure mode is a "not valid"
        latency = int((time.perf_counter() - started) * 1000)
        logger.info("credential validation failed for %s: %s", provider, str(exc)[:200])
        return ValidationResult(False, provider, resolved_model, _friendly_error(exc), latency)

    return ValidationResult(
        True, provider, resolved_model, "", int((time.perf_counter() - started) * 1000)
    )


def _friendly_error(exc: Exception) -> str:
    """Translate provider exceptions into something a user can act on."""
    text = str(exc)
    lowered = text.lower()

    if "401" in text or "invalid api key" in lowered or "unauthorized" in lowered:
        return "The provider rejected this API key. Check that it is complete and active."
    if "429" in text or "rate limit" in lowered:
        return "The provider rate-limited this key. It may still be valid — try again shortly."
    # Providers word this several ways, and a retired model is the single most
    # common cause: the id was valid when it was written down, and is not now.
    if (
        "model_not_found" in lowered
        or "does not exist" in lowered
        or "not a valid model" in lowered
        or "no such model" in lowered
        or "model not found" in lowered
        or ("model" in lowered and "decommission" in lowered)
        or ("model" in lowered and "deprecat" in lowered)
    ):
        return (
            "The provider does not recognise that model id — it may have been retired. "
            "Use Detect models in Settings to list what the provider currently serves."
        )
    if "connection" in lowered or "timeout" in lowered or "connect" in lowered:
        return "Could not reach the provider. Check your network, or the base URL for Ollama."
    if isinstance(exc, UpstreamError):
        return text
    return text[:300]


def _env_var_for(provider: str) -> str:
    return {
        "groq": "GROQ_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "openai": "OPENAI_API_KEY",
        "custom": "CUSTOM_API_KEY",
    }.get(provider, f"{provider.upper()}_API_KEY")
