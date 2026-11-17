"""Groq-specific CrewAI message compatibility."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from crewai import LLM


class GroqCompatibleLLM(LLM):
    """CrewAI LLM that removes Groq's unsupported cache marker per request."""

    def _prepare_completion_params(
        self,
        messages: str | list[Any],
        tools: list[dict[str, Any]] | None = None,
        skip_file_processing: bool = False,
    ) -> dict[str, Any]:
        params = super()._prepare_completion_params(
            messages,
            tools,
            skip_file_processing,
        )
        prepared_messages = params.get("messages")
        if not isinstance(prepared_messages, list):
            return params

        sanitized_messages = deepcopy(prepared_messages)
        for message in sanitized_messages:
            if isinstance(message, dict):
                message.pop("cache_breakpoint", None)
        params["messages"] = sanitized_messages
        return params
