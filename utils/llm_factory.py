"""
LLM Factory — creates provider-specific crewai.LLM instances for each agent.
Supports: Groq, Gemini, OpenAI, Ollama (local).
Keys read from session_state (Streamlit or mocked) with .env fallback.
"""

import sys
import os
from typing import Optional, Literal

from pydantic import BaseModel
from crewai import LLM
import litellm

# Ensure litellm drops unsupported provider params (such as cache_breakpoint on Groq)
litellm.drop_params = True

# Patch litellm.completion & litellm.acompletion to strip unsupported keys inside message dicts (e.g. cache_breakpoint on Groq)
_orig_completion = getattr(litellm, "completion", None)
_orig_acompletion = getattr(litellm, "acompletion", None)

def _clean_messages(messages):
    if not isinstance(messages, list):
        return messages
    cleaned = []
    for msg in messages:
        if isinstance(msg, dict):
            clean_msg = {k: v for k, v in msg.items() if k not in ("cache_breakpoint", "cache_control")}
            cleaned.append(clean_msg)
        else:
            cleaned.append(msg)
    return cleaned

GROQ_FALLBACK_MODELS = [
    "groq/llama-3.1-8b-instant",
    "groq/llama-3.3-70b-versatile",
    "groq/mixtral-8x7b-32768",
    "groq/gemma2-9b-it"
]

if _orig_completion:
    def _sanitized_completion(*args, **kwargs):
        if "messages" in kwargs:
            kwargs["messages"] = _clean_messages(kwargs["messages"])
        current_model = kwargs.get("model", "")
        try:
            return _orig_completion(*args, **kwargs)
        except litellm.NotFoundError as e:
            if "groq" in str(current_model).lower() or "model_not_found" in str(e).lower():
                for fallback in GROQ_FALLBACK_MODELS:
                    if fallback != current_model:
                        try:
                            kwargs["model"] = fallback
                            return _orig_completion(*args, **kwargs)
                        except Exception:
                            continue
            raise e
    litellm.completion = _sanitized_completion

if _orig_acompletion:
    async def _sanitized_acompletion(*args, **kwargs):
        if "messages" in kwargs:
            kwargs["messages"] = _clean_messages(kwargs["messages"])
        current_model = kwargs.get("model", "")
        try:
            return await _orig_acompletion(*args, **kwargs)
        except litellm.NotFoundError as e:
            if "groq" in str(current_model).lower() or "model_not_found" in str(e).lower():
                for fallback in GROQ_FALLBACK_MODELS:
                    if fallback != current_model:
                        try:
                            kwargs["model"] = fallback
                            return await _orig_acompletion(*args, **kwargs)
                        except Exception:
                            continue
            raise e
    litellm.acompletion = _sanitized_acompletion

ProviderName = Literal["groq", "gemini", "openai", "ollama"]


class AgentLLMConfig(BaseModel):
    """Per-agent LLM configuration."""
    provider: ProviderName = "groq"
    api_key: str = ""
    model: str = ""
    base_url: str = ""  # For Ollama
    temperature: float = 0.2
    max_tokens: int = 4096


# Default models per provider (tuned for high stability & free tier)
DEFAULT_MODELS: dict[ProviderName, str] = {
    "groq": "llama-3.1-8b-instant",
    "gemini": "gemini-1.5-flash",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.1",
}


def _get_session_config() -> dict[str, AgentLLMConfig]:
    """Get per-agent config dynamically from session state."""
    st_mod = sys.modules.get("streamlit")
    if st_mod and hasattr(st_mod, "session_state"):
        sess = st_mod.session_state
        if isinstance(sess, dict):
            return sess.get("llm_config", {})
        elif hasattr(sess, "get"):
            return sess.get("llm_config", {})
    return {}


def _get_env_fallback(provider: ProviderName) -> str:
    """Get API key from environment variables."""
    env_map = {
        "groq": "GROQ_API_KEY",
        "gemini": "GOOGLE_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    env_var = env_map.get(provider)
    if env_var:
        return os.getenv(env_var, "")
    return ""


def _resolve_key(config: AgentLLMConfig, use_global: bool, global_key: str) -> str:
    """Resolve API key: global (if use_global) > agent-specific > env."""
    if use_global and global_key:
        return global_key.strip()
    if config.api_key:
        return config.api_key.strip()
    return _get_env_fallback(config.provider)


def _resolve_model(config: AgentLLMConfig) -> str:
    """Resolve model name with provider default fallback."""
    if config.model:
        return config.model
    return DEFAULT_MODELS.get(config.provider, "llama-3.3-70b-versatile")


def format_model_string(provider: ProviderName, model: str) -> str:
    """Ensure model string has proper provider prefix for crewai / litellm."""
    model = model.strip()
    if provider == "groq" and not model.startswith("groq/"):
        return f"groq/{model}"
    if provider == "gemini" and not model.startswith("gemini/"):
        return f"gemini/{model}"
    if provider == "openai" and not model.startswith("openai/"):
        return f"openai/{model}"
    if provider == "ollama" and not model.startswith("ollama/"):
        return f"ollama/{model}"
    return model


def create_llm(
    agent_name: str,
    *,
    use_global_key: bool = False,
    global_key: str = "",
) -> LLM:
    """
    Create a crewai.LLM instance for the given agent.

    Args:
        agent_name: One of "researcher", "web_searcher", "analyst", "summarizer"
        use_global_key: Whether to use a single key for all agents
        global_key: The global key if use_global_key is True

    Returns:
        Configured crewai.LLM instance

    Raises:
        ValueError: If API key missing for non-Ollama providers
    """
    configs = _get_session_config()
    config = configs.get(agent_name, AgentLLMConfig())

    st_mod = sys.modules.get("streamlit")
    if st_mod and hasattr(st_mod, "session_state"):
        sess = st_mod.session_state
        if isinstance(sess, dict):
            if sess.get("use_global_key") or use_global_key:
                use_global_key = True
                if not global_key and sess.get("global_key"):
                    global_key = sess["global_key"]
                provider = sess.get("global_provider", config.provider)
            else:
                provider = config.provider
        elif hasattr(sess, "get"):
            if sess.get("use_global_key") or use_global_key:
                use_global_key = True
                if not global_key and sess.get("global_key"):
                    global_key = sess.get("global_key", "")
                provider = sess.get("global_provider", config.provider)
            else:
                provider = config.provider
    else:
        provider = config.provider

    raw_model = _resolve_model(config)
    model = format_model_string(provider, raw_model)
    api_key = _resolve_key(config, use_global_key, global_key)
    temperature = config.temperature
    max_tokens = config.max_tokens
    base_url = config.base_url or None

    if provider != "ollama" and not api_key:
        env_var_name = {"groq": "GROQ_API_KEY", "gemini": "GOOGLE_API_KEY", "openai": "OPENAI_API_KEY"}.get(provider, "")
        raise ValueError(f"{provider.capitalize()} API key required for agent '{agent_name}'. Set in Settings or .env ({env_var_name})")

    if provider == "ollama":
        return LLM(
            model=model,
            base_url=base_url or "http://localhost:11434",
            temperature=temperature,
            drop_params=True,
        )

    return LLM(
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
        drop_params=True,
    )


def validate_key(provider: ProviderName, api_key: str, model: str = "") -> tuple[bool, str]:
    """
    Lightweight validation ping for an API key.
    Returns (is_valid, error_message).
    """
    if not api_key and provider != "ollama":
        return False, "API key is empty"

    try:
        raw_model = model or DEFAULT_MODELS.get(provider, "")
        formatted_model = format_model_string(provider, raw_model)
        llm = LLM(
            model=formatted_model,
            api_key=api_key if provider != "ollama" else None,
            max_tokens=10,
            drop_params=True,
        )
        llm.call(messages=[{"role": "user", "content": "ping"}])
        return True, ""
    except Exception as e:
        return False, str(e)[:120]


def get_available_providers() -> list[ProviderName]:
    """Return list of supported providers."""
    return ["groq", "gemini", "openai", "ollama"]


def get_default_model(provider: ProviderName) -> str:
    """Get default model for a provider."""
    return DEFAULT_MODELS.get(provider, "llama-3.3-70b-versatile")