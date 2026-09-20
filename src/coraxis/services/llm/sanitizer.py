"""LiteLLM compatibility patches.

Two problems, both real, both discovered the hard way:

1. Some provider adapters inject ``cache_breakpoint`` / ``cache_control`` keys
   into message dicts. Groq rejects them outright, and the failure surfaces as
   an opaque 400 from deep inside the provider adapter.
2. Groq retires models on a schedule. A pinned model id starts returning
   ``model_not_found`` with no warning, which would otherwise take the whole
   pipeline down.

Both are handled here rather than at the call site, so every LLM created by the
factory benefits. The patch is applied once per process and is idempotent.
"""

from __future__ import annotations

import threading
from typing import Any

import litellm

from coraxis.core.logging import get_logger

logger = get_logger("llm.sanitizer")

#: Models to fall back to, in order, when a Groq model id is retired.
#:
#: This list must stay on models available to the *developer* tier. Its
#: previous contents were four dead ids — ``mixtral-8x7b-32768`` and
#: ``gemma2-9b-it`` were decommissioned, and both Llama ids moved to
#: Enterprise-only — so a failing call retried four more models that also
#: failed, and the user saw a wall of model errors with no way to tell which
#: one was real.
GROQ_FALLBACK_MODELS: tuple[str, ...] = (
    "groq/openai/gpt-oss-120b",
    "groq/openai/gpt-oss-20b",
    "groq/qwen/qwen3.8-27b",
)

#: Keys some adapters add that most providers reject.
_UNSUPPORTED_MESSAGE_KEYS = frozenset({"cache_breakpoint", "cache_control"})

_patch_lock = threading.Lock()
_patched = False


def clean_messages(messages: Any) -> Any:
    """Strip provider-incompatible keys from a message list."""
    if not isinstance(messages, list):
        return messages

    cleaned = []
    for message in messages:
        if isinstance(message, dict):
            cleaned.append(
                {
                    key: value
                    for key, value in message.items()
                    if key not in _UNSUPPORTED_MESSAGE_KEYS
                }
            )
        else:
            cleaned.append(message)
    return cleaned


def _is_missing_model_error(exc: Exception, model: str) -> bool:
    text = str(exc).lower()
    return "groq" in str(model).lower() or "model_not_found" in text or "does not exist" in text


def apply_litellm_patches() -> None:
    """Install the message sanitiser and Groq fallback. Idempotent."""
    global _patched
    with _patch_lock:
        if _patched:
            return
        _patched = True

    # Ask LiteLLM to drop parameters a provider does not accept, rather than
    # failing the request.
    litellm.drop_params = True

    original_completion = getattr(litellm, "completion", None)
    original_acompletion = getattr(litellm, "acompletion", None)

    if original_completion is not None:

        def completion_with_fallback(*args: Any, **kwargs: Any) -> Any:
            if "messages" in kwargs:
                kwargs["messages"] = clean_messages(kwargs["messages"])
            model = kwargs.get("model", "")
            try:
                return original_completion(*args, **kwargs)
            except litellm.NotFoundError as exc:
                if not _is_missing_model_error(exc, model):
                    raise
                return _retry_with_fallback(
                    original_completion, args, kwargs, model, synchronous=True
                )

        litellm.completion = completion_with_fallback  # type: ignore[assignment]

    if original_acompletion is not None:

        async def acompletion_with_fallback(*args: Any, **kwargs: Any) -> Any:
            if "messages" in kwargs:
                kwargs["messages"] = clean_messages(kwargs["messages"])
            model = kwargs.get("model", "")
            try:
                return await original_acompletion(*args, **kwargs)
            except litellm.NotFoundError as exc:
                if not _is_missing_model_error(exc, model):
                    raise
                return await _aretry_with_fallback(original_acompletion, args, kwargs, model)

        litellm.acompletion = acompletion_with_fallback  # type: ignore[assignment]

    logger.debug("litellm patches applied")


def _retry_with_fallback(
    original: Any, args: tuple, kwargs: dict, model: str, *, synchronous: bool
) -> Any:
    last_error: Exception | None = None
    for fallback in GROQ_FALLBACK_MODELS:
        if fallback == model:
            continue
        logger.warning("model %s unavailable; retrying with %s", model, fallback)
        try:
            return original(*args, **{**kwargs, "model": fallback})
        except Exception as exc:  # noqa: BLE001 - try the next candidate
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("No Groq fallback model succeeded.")


async def _aretry_with_fallback(original: Any, args: tuple, kwargs: dict, model: str) -> Any:
    last_error: Exception | None = None
    for fallback in GROQ_FALLBACK_MODELS:
        if fallback == model:
            continue
        logger.warning("model %s unavailable; retrying with %s", model, fallback)
        try:
            return await original(*args, **{**kwargs, "model": fallback})
        except Exception as exc:  # noqa: BLE001 - try the next candidate
            last_error = exc
    if last_error is not None:
        raise last_error
    raise RuntimeError("No Groq fallback model succeeded.")


def reset_patch_state() -> None:
    """Allow re-patching. Tests only."""
    global _patched
    with _patch_lock:
        _patched = False
