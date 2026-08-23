"""
LLM Factory — creates provider-specific crewai.LLM instances for each agent.
Supports: Groq, Gemini, OpenAI, Ollama (local).
Keys read from st.session_state.llm_config with .env fallback.
"""

import os
from typing import Optional, Literal

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore

from pydantic import BaseModel
from crewai import LLM

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
    "groq": "llama-3.3-70b-versatile",
    "gemini": "gemini-1.5-flash",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.1",
}


def _get_session_config() -> dict[str, AgentLLMConfig]:
    """Get per-agent config from session state."""
    if st and hasattr(st, "session_state"):
        return st.session_state.get("llm_config", {})
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
    """Resolve API key: agent-specific > global > env."""
    if config.api_key:
        return config.api_key
    if use_global and global_key:
        return global_key
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
        )

    return LLM(
        model=model,
        api_key=api_key,
        temperature=temperature,
        max_tokens=max_tokens,
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