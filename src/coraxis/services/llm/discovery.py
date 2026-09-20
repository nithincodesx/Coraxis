"""Live model catalogue lookup.

Provider model lists change constantly — models get retired, renamed, or moved
behind an enterprise tier. A hardcoded default goes stale silently and the user
only finds out when a run fails with an opaque provider error. Asking the
provider what it currently serves removes that whole class of failure.

Everything here is best-effort: a catalogue lookup failing must never block a
save, so errors come back as a message rather than an exception.
"""

from __future__ import annotations

import httpx

from coraxis.core.errors import ConfigurationError
from coraxis.core.logging import get_logger
from coraxis.db.enums import DEFAULT_BASE_URLS, OPENAI_COMPATIBLE

logger = get_logger("llm.discovery")

_TIMEOUT = httpx.Timeout(15.0, connect=8.0)

#: Substrings that mark a model as something other than a chat completion
#: model. Providers list speech, embedding and moderation models alongside
#: chat models, and offering them in a "pick a model" dropdown is a trap.
_NON_CHAT_MARKERS = (
    "whisper",
    "tts",
    "text-to-speech",
    "speech",
    "audio",
    "embed",
    "embedding",
    "rerank",
    "moderation",
    "guard",
    "safeguard",
    "dall-e",
    "image",
    "vision-only",
    "orpheus",
    "stable-diffusion",
    "flux",
)


def _looks_like_chat_model(model_id: str) -> bool:
    lowered = model_id.lower()
    return not any(marker in lowered for marker in _NON_CHAT_MARKERS)


def _catalogue_url(provider: str, base_url: str) -> str:
    """Resolve the models endpoint for a provider."""
    if provider == "gemini":
        return "https://generativelanguage.googleapis.com/v1beta/models"

    base = (base_url or DEFAULT_BASE_URLS.get(provider, "")).strip().rstrip("/")
    if not base:
        raise ConfigurationError(
            "This provider needs a base URL before its models can be listed — "
            "for example https://api.inceptionlabs.ai/v1"
        )
    return f"{base}/models"


def _parse_catalogue(payload: object) -> list[str]:
    """Pull model ids out of either catalogue shape.

    OpenAI-compatible providers return ``{"data": [{"id": ...}]}``. Gemini
    returns ``{"models": [{"name": "models/gemini-2.5-flash"}]}`` and strips the
    ``models/`` prefix for you when calling, so we do it here too.
    """
    if not isinstance(payload, dict):
        return []

    ids: list[str] = []

    data = payload.get("data")
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and isinstance(entry.get("id"), str):
                ids.append(entry["id"])

    models = payload.get("models")
    if isinstance(models, list):
        for entry in models:
            if isinstance(entry, dict):
                name = entry.get("name")
                if isinstance(name, str):
                    ids.append(name.removeprefix("models/"))

    return ids


async def list_provider_models(
    provider: str,
    api_key: str = "",
    base_url: str = "",
) -> tuple[list[str], str]:
    """Return ``(model_ids, error)`` for a provider.

    Chat-capable models are listed first, in provider order. If the filter
    removes everything — a provider we have no heuristics for — the raw list is
    returned rather than an empty dropdown.
    """
    try:
        url = _catalogue_url(provider, base_url)
    except ConfigurationError as exc:
        return [], str(exc)

    headers: dict[str, str] = {}
    params: dict[str, str] = {}

    if provider == "gemini":
        # Gemini authenticates the catalogue with a query parameter, not a header.
        if not api_key.strip():
            return [], "Gemini needs an API key to list models."
        params["key"] = api_key
    elif provider in OPENAI_COMPATIBLE and provider != "ollama":
        # Ollama runs locally and is keyless; everything else here wants a
        # bearer token.
        if not api_key.strip():
            return [], "Enter an API key first — the provider needs it to list models."
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=headers, params=params)
    except httpx.TimeoutException:
        return [], "The provider did not respond in time. Check the base URL."
    except httpx.RequestError as exc:
        logger.info("model discovery could not reach %s: %s", provider, exc)
        return [], "Could not reach that endpoint. Check the base URL and your network."

    if response.status_code in (401, 403):
        return [], "The provider rejected this API key."
    if response.status_code == 404:
        return [], (
            "That endpoint has no /models route. Most OpenAI-compatible platforms "
            "expose one at <base-url>/models — check the base URL."
        )
    if response.status_code >= 400:
        return [], f"The provider returned HTTP {response.status_code} for the model list."

    try:
        payload = response.json()
    except ValueError:
        return [], "The provider returned a response that is not JSON."

    ids = _parse_catalogue(payload)
    if not ids:
        return [], "The provider returned no models in a shape we recognise."

    chat_models = [model for model in ids if _looks_like_chat_model(model)]
    # Never return an empty list just because the heuristics missed.
    chosen = chat_models or ids

    logger.info("discovered %d models for %s", len(chosen), provider)
    return sorted(chosen), ""
