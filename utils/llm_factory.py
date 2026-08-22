"""
LLM Factory — creates provider-specific LLM instances for each agent.
Supports: Groq, Gemini, OpenAI, Ollama (local).
Keys read from st.session_state.llm_config with .env fallback.
"""

import os
from typing import Optional, Literal
from functools import lru_cache

try:
    import streamlit as st
except ImportError:
    st = None  # type: ignore

from langchain_core.language_models.chat_models import BaseChatModel
from pydantic import BaseModel, Field

# Provider imports (lazy to avoid hard deps)
_GROQ_AVAILABLE = False
_GEMINI_AVAILABLE = False
_OPENAI_AVAILABLE = False
_OLLAMA_AVAILABLE = False

try:
    from langchain_groq import ChatGroq
    _GROQ_AVAILABLE = True
except ImportError:
    pass

try:
    from langchain_google_genai import ChatGoogleGenerativeAI
    _GEMINI_AVAILABLE = True
except ImportError:
    pass

try:
    from langchain_openai import ChatOpenAI
    _OPENAI_AVAILABLE = True
except ImportError:
    pass

try:
    from langchain_community.chat_models import ChatOllama
    _OLLAMA_AVAILABLE = True
except ImportError:
    pass


ProviderName = Literal["groq", "gemini", "openai", "ollama"]


class AgentLLMConfig(BaseModel):
    """Per-agent LLM configuration."""
    provider: ProviderName = "groq"
    api_key: str = ""
    model: str = ""
    base_url: str = ""  # For Ollama
    temperature: float = 0.2
    max_tokens: int = 4096


# Default models per provider (tuned for free tier & small keys)
DEFAULT_MODELS: dict[ProviderName, str] = {
    "groq": "llama-3.1-8b-instant",
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
    return DEFAULT_MODELS.get(config.provider, "llama-3.1-8b-instant")



def create_llm(
    agent_name: str,
    *,
    use_global_key: bool = False,
    global_key: str = "",
) -> BaseChatModel:
    """
    Create an LLM instance for the given agent.

    Args:
        agent_name: One of "researcher", "web_searcher", "analyst", "summarizer"
        use_global_key: Whether to use a single key for all agents
        global_key: The global key if use_global_key is True

    Returns:
        Configured BaseChatModel instance

    Raises:
        ValueError: If provider not available or key missing
    """
    configs = _get_session_config()
    config = configs.get(agent_name, AgentLLMConfig())

    provider = config.provider
    model = _resolve_model(config)
    api_key = _resolve_key(config, use_global_key, global_key)
    temperature = config.temperature
    max_tokens = config.max_tokens
    base_url = config.base_url or None

    if provider == "groq":
        if not _GROQ_AVAILABLE:
            raise ValueError("langchain-groq not installed. Run: pip install langchain-groq")
        if not api_key:
            raise ValueError("Groq API key required. Set in Settings or .env (GROQ_API_KEY)")
        return ChatGroq(
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            max_retries=2,
            timeout=60,
        )

    if provider == "gemini":
        if not _GEMINI_AVAILABLE:
            raise ValueError("langchain-google-genai not installed. Run: pip install langchain-google-genai")
        if not api_key:
            raise ValueError("Google API key required. Set in Settings or .env (GOOGLE_API_KEY)")
        return ChatGoogleGenerativeAI(
            model=model,
            google_api_key=api_key,
            temperature=temperature,
            max_output_tokens=max_tokens,
            convert_system_message_to_human=True,
        )

    if provider == "openai":
        if not _OPENAI_AVAILABLE:
            raise ValueError("langchain-openai not installed. Run: pip install langchain-openai")
        if not api_key:
            raise ValueError("OpenAI API key required. Set in Settings or .env (OPENAI_API_KEY)")
        return ChatOpenAI(
            model=model,
            api_key=api_key,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=60,
            max_retries=2,
        )

    if provider == "ollama":
        if not _OLLAMA_AVAILABLE:
            raise ValueError("langchain-community not installed. Run: pip install langchain-community")
        return ChatOllama(
            model=model,
            base_url=base_url or "http://localhost:11434",
            temperature=temperature,
            num_predict=max_tokens,
        )

    raise ValueError(f"Unknown provider: {provider}")


def validate_key(provider: ProviderName, api_key: str, model: str = "") -> tuple[bool, str]:
    """
    Lightweight validation ping for an API key.
    Returns (is_valid, error_message).
    """
    if not api_key and provider != "ollama":
        return False, "API key is empty"

    try:
        if provider == "groq" and _GROQ_AVAILABLE:
            llm = ChatGroq(model=model or DEFAULT_MODELS["groq"], api_key=api_key, max_tokens=10, timeout=10)
            llm.invoke("ping")
            return True, ""
        elif provider == "gemini" and _GEMINI_AVAILABLE:
            llm = ChatGoogleGenerativeAI(model=model or DEFAULT_MODELS["gemini"], google_api_key=api_key, max_output_tokens=10)
            llm.invoke("ping")
            return True, ""
        elif provider == "openai" and _OPENAI_AVAILABLE:
            llm = ChatOpenAI(model=model or DEFAULT_MODELS["openai"], api_key=api_key, max_tokens=10, timeout=10)
            llm.invoke("ping")
            return True, ""
        elif provider == "ollama" and _OLLAMA_AVAILABLE:
            llm = ChatOllama(model=model or DEFAULT_MODELS["ollama"], num_predict=10)
            llm.invoke("ping")
            return True, ""
        else:
            return False, f"Provider {provider} not available (missing package)"
    except Exception as e:
        return False, str(e)[:120]


def get_available_providers() -> list[ProviderName]:
    """Return list of providers with installed packages."""
    providers = []
    if _GROQ_AVAILABLE: providers.append("groq")
    if _GEMINI_AVAILABLE: providers.append("gemini")
    if _OPENAI_AVAILABLE: providers.append("openai")
    if _OLLAMA_AVAILABLE: providers.append("ollama")
    return providers


def get_default_model(provider: ProviderName) -> str:
    """Get default model for a provider."""
    return DEFAULT_MODELS.get(provider, "llama-3.3-70b-versatile")