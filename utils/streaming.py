"""
Streaming Callback Handler — Bridges CrewAI execution to Streamlit UI updates.
Updates timeline, activity feed, and progress in real-time.
"""

import time
import streamlit as st
from typing import Optional, Any
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from components.timeline import (
    start_agent,
    update_agent_progress,
    complete_agent,
    get_agent_state,
)
from components.activity_feed import (
    log_agent_start,
    log_agent_progress,
    log_agent_complete,
    log_agent_error,
)


class StreamlitCallbackHandler(BaseCallbackHandler):
    """
    CrewAI/LangChain callback handler that updates Streamlit session state
    for real-time UI updates during agent execution.
    """

    def __init__(self):
        self.current_agent: Optional[str] = None
        self.agent_start_times: dict[str, float] = {}
        self.token_counts: dict[str, int] = {}
        self.agent_step_counts: dict[str, int] = {}

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        **kwargs,
    ) -> None:
        """Chain start - could be agent or task start."""
        # Check if this is an agent chain
        name = serialized.get("name", "").lower()
        if "researcher" in name:
            self._set_agent("researcher")
        elif "web_searcher" in name or "search" in name:
            self._set_agent("web_searcher")
        elif "analyst" in name:
            self._set_agent("analyst")
        elif "summarizer" in name or "writer" in name:
            self._set_agent("summarizer")

    def on_chain_end(self, outputs: dict[str, Any], **kwargs) -> None:
        """Chain end - agent completed."""
        if self.current_agent:
            complete_agent(self.current_agent, success=True)
            log_agent_complete(self.current_agent, "Task completed")
            self.current_agent = None

    def on_chain_error(self, error: BaseException, **kwargs) -> None:
        """Chain error."""
        if self.current_agent:
            complete_agent(self.current_agent, success=False, error=str(error)[:100])
            log_agent_error(self.current_agent, str(error)[:100])
            self.current_agent = None

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        **kwargs,
    ) -> None:
        """LLM start - track token usage."""
        if self.current_agent:
            self.token_counts[self.current_agent] = self.token_counts.get(self.current_agent, 0) + len(prompts[0]) // 4

    def on_llm_end(self, response: LLMResult, **kwargs) -> None:
        """LLM end - update progress based on token generation."""
        if self.current_agent:
            # Rough progress estimation based on token count
            tokens = sum(len(g.text) for g in response.generations[0]) // 4
            self.token_counts[self.current_agent] = self.token_counts.get(self.current_agent, 0) + tokens
            # Update progress (capped, real progress comes from task completion)
            progress = min(90, self.token_counts[self.current_agent] // 20)
            update_agent_progress(self.current_agent, progress)

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        **kwargs,
    ) -> None:
        """Tool start - log activity."""
        tool_name = serialized.get("name", "")
        if self.current_agent:
            self.agent_step_counts[self.current_agent] = self.agent_step_counts.get(self.current_agent, 0) + 1
            step = self.agent_step_counts[self.current_agent]
            if "search" in tool_name.lower():
                log_agent_progress(self.current_agent, f"🔍 Searching: {input_str[:60]}")
            elif "fetch" in tool_name.lower():
                log_agent_progress(self.current_agent, f"📄 Fetching page...")
            elif "memory" in tool_name.lower() or "recall" in tool_name.lower():
                log_agent_progress(self.current_agent, f"🧠 Checking memory...")
            elif "register" in tool_name.lower() or "claim" in tool_name.lower():
                log_agent_progress(self.current_agent, f"📝 Registering claim...")

    def on_tool_end(self, output: str, **kwargs) -> None:
        """Tool end - log result."""
        if self.current_agent:
            # Try to extract useful info from output
            try:
                import json
                data = json.loads(output)
                if isinstance(data, list) and data:
                    log_agent_progress(self.current_agent, f"✅ Got {len(data)} results")
                elif isinstance(data, dict) and "word_count" in data:
                    log_agent_progress(self.current_agent, f"✅ Fetched {data.get('word_count', 0)} words")
                elif isinstance(data, dict) and "claim_ids" in data:
                    log_agent_progress(self.current_agent, f"✅ Registered claim")
            except Exception:
                pass

    def on_tool_error(self, error: BaseException, **kwargs) -> None:
        """Tool error."""
        if self.current_agent:
            log_agent_progress(self.current_agent, f"⚠️ Tool error: {str(error)[:60]}", "warning")

    def _set_agent(self, agent_key: str):
        """Set current agent and initialize tracking."""
        if self.current_agent != agent_key:
            # Complete previous agent if any
            if self.current_agent:
                complete_agent(self.current_agent, success=True)
                log_agent_complete(self.current_agent)

            self.current_agent = agent_key
            self.agent_start_times[agent_key] = time.time()
            self.token_counts[agent_key] = 0
            self.agent_step_counts[agent_key] = 0

            start_agent(agent_key)
            log_agent_start(agent_key)


# Global handler instance
_handler: Optional[StreamlitCallbackHandler] = None


def get_streaming_handler() -> StreamlitCallbackHandler:
    """Get or create the global streaming handler."""
    global _handler
    if _handler is None:
        _handler = StreamlitCallbackHandler()
    return _handler


def reset_streaming_handler():
    """Reset the streaming handler for a new run."""
    global _handler
    _handler = StreamlitCallbackHandler()


# Manual progress update functions (for non-LLM steps)
def set_agent_running(agent_key: str, detail: str = ""):
    """Manually mark agent as running."""
    start_agent(agent_key)
    log_agent_start(agent_key, detail)


def set_agent_progress(agent_key: str, progress: int, detail: str = ""):
    """Manually update agent progress."""
    update_agent_progress(agent_key, progress)
    if detail:
        log_agent_progress(agent_key, detail)


def set_agent_done(agent_key: str, detail: str = "", success: bool = True, error: str = ""):
    """Manually mark agent as done."""
    complete_agent(agent_key, success=success, error=error)
    if success:
        log_agent_complete(agent_key, detail)
    else:
        log_agent_error(agent_key, error)