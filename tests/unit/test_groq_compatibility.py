"""Regression tests for the instance-local Groq CrewAI adapter."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from coraxis.services.llm.factory import LLMConfig, build_llm
from coraxis.services.llm.groq_compat import GroqCompatibleLLM


def _messages() -> list[dict[str, Any]]:
    return [
        {
            "role": "system",
            "content": "system",
            "cache_breakpoint": True,
            "metadata": {"keep": True},
        },
        {
            "role": "assistant",
            "content": "call",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "echo", "arguments": '{"text":"x"}'},
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": "tool result",
        },
    ]


def test_groq_adapter_removes_only_cache_breakpoint_without_mutation() -> None:
    llm = GroqCompatibleLLM(
        model="groq/openai/gpt-oss-120b",
        api_key="test-key",
        temperature=0,
    )
    messages = _messages()
    original = deepcopy(messages)

    prepared = llm._prepare_completion_params(messages)

    assert messages == original
    sanitized = prepared["messages"]
    assert isinstance(sanitized, list)
    assert "cache_breakpoint" not in sanitized[0]
    assert sanitized[0]["metadata"] == {"keep": True}
    assert sanitized[0]["role"] == "system"
    assert sanitized[1]["tool_calls"] == original[1]["tool_calls"]
    assert sanitized[2] == original[2]


def test_groq_adapter_handles_multiple_messages_and_nested_metadata() -> None:
    llm = GroqCompatibleLLM(model="groq/openai/gpt-oss-120b", api_key="test-key")
    messages = [
        {
            "role": "user",
            "content": [{"type": "text", "text": "hello", "cache_breakpoint": "nested"}],
            "metadata": {"cache_breakpoint": "unrelated"},
            "cache_breakpoint": True,
        },
        {"role": "assistant", "content": "done"},
    ]

    prepared = llm._prepare_completion_params(messages)

    assert prepared["messages"][0]["content"][0]["cache_breakpoint"] == "nested"
    assert prepared["messages"][0]["metadata"]["cache_breakpoint"] == "unrelated"
    assert len(prepared["messages"]) == 2


def test_non_groq_build_path_returns_standard_llm() -> None:
    llm = build_llm(
        LLMConfig(
            agent_slug="openai-agent",
            provider="openai",
            model="gpt-4o-mini",
            api_key="test-key",
        )
    )

    assert not isinstance(llm, GroqCompatibleLLM)
    assert llm.model == "gpt-4o-mini"


def test_groq_build_path_returns_instance_local_adapter() -> None:
    llm = build_llm(
        LLMConfig(
            agent_slug="groq-agent",
            provider="groq",
            model="openai/gpt-oss-120b",
            api_key="test-key",
        )
    )

    assert isinstance(llm, GroqCompatibleLLM)


def test_groq_adapter_preserves_every_non_cache_breakpoint_top_level_property() -> None:
    """Only the top-level ``cache_breakpoint`` key is removed; nothing else."""
    llm = GroqCompatibleLLM(model="groq/openai/gpt-oss-120b", api_key="test-key")
    messages = [
        {
            "role": "system",
            "content": "system prompt",
            "name": "system",
            "cache_breakpoint": True,
        },
        {
            "role": "assistant",
            "content": "assistant text",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {"name": "echo", "arguments": '{"text":"x"}'},
                }
            ],
            "cache_breakpoint": True,
        },
        {
            "role": "tool",
            "tool_call_id": "call-1",
            "content": "tool result",
        },
        {
            "role": "function",
            "name": "echo",
            "content": '{"ok": true}',
        },
    ]
    original = deepcopy(messages)

    prepared = llm._prepare_completion_params(messages)

    assert messages == original  # input not mutated
    sanitized = prepared["messages"]
    assert len(sanitized) == len(messages)

    # cache_breakpoint removed only at the top level of each message.
    for message in sanitized:
        assert "cache_breakpoint" not in message

    # Every other top-level property is preserved exactly.
    assert sanitized[0]["role"] == "system"
    assert sanitized[0]["content"] == "system prompt"
    assert sanitized[0]["name"] == "system"
    assert sanitized[1]["role"] == "assistant"
    assert sanitized[1]["content"] == "assistant text"
    assert sanitized[1]["tool_calls"] == original[1]["tool_calls"]
    assert sanitized[2]["role"] == "tool"
    assert sanitized[2]["tool_call_id"] == "call-1"
    assert sanitized[2]["content"] == "tool result"
    assert sanitized[3]["role"] == "function"
    assert sanitized[3]["name"] == "echo"
    assert sanitized[3]["content"] == '{"ok": true}'


def test_groq_adapter_does_not_monkey_patch_base_llm() -> None:
    """Creating a GroqCompatibleLLM must not alter CrewAI's base LLM class.

    The cache_breakpoint stripping must be instance/local to the Groq subclass,
    not a process-wide monkey patch on the base LLM.
    """
    from crewai import LLM as BaseLLM

    GroqCompatibleLLM(model="groq/openai/gpt-oss-120b", api_key="test-key")

    # The override lives only on the subclass, not on the base class.
    assert GroqCompatibleLLM._prepare_completion_params is not BaseLLM._prepare_completion_params

    # A standard LLM instance still keeps cache_breakpoint intact.
    standard = BaseLLM(model="openai/gpt-4o-mini")
    params = standard._prepare_completion_params(
        [{"role": "user", "content": "hi", "cache_breakpoint": True}]
    )
    assert params["messages"][0]["cache_breakpoint"] is True
