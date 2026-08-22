"""
Utils package — LLM factory, streaming callbacks, export utilities.
"""

from .llm_factory import (
    create_llm,
    validate_key,
    get_available_providers,
    get_default_model,
    AgentLLMConfig,
    ProviderName,
)
from .streaming import (
    StreamlitCallbackHandler,
    get_streaming_handler,
    reset_streaming_handler,
    set_agent_running,
    set_agent_progress,
    set_agent_done,
)
from .export import (
    export_markdown,
    export_pdf,
    export_html,
)

__all__ = [
    "create_llm",
    "validate_key",
    "get_available_providers",
    "get_default_model",
    "AgentLLMConfig",
    "ProviderName",
    "StreamlitCallbackHandler",
    "get_streaming_handler",
    "reset_streaming_handler",
    "set_agent_running",
    "set_agent_progress",
    "set_agent_done",
    "export_markdown",
    "export_pdf",
    "export_html",
]