"""Enumerations shared by the database models, schemas, and services.

Stored as short strings rather than native SQL enums so the same migrations
work unchanged on SQLite and Postgres, and so adding a value never requires an
``ALTER TYPE``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

#: Supported LLM providers. Kept here rather than in the LLM service so that
#: schemas can validate against it without importing business logic.
#:
#: ``custom`` is any OpenAI-compatible endpoint the user supplies a base URL
#: for — Inception, Together, OpenRouter, DeepSeek, a local vLLM, anything that
#: speaks ``/chat/completions``. It exists so adding a provider never requires
#: a code change.
ProviderName = Literal["groq", "gemini", "openai", "ollama", "custom"]

PROVIDERS: tuple[str, ...] = ("groq", "gemini", "openai", "ollama", "custom")

#: Sensible free-tier-friendly default per provider.
#:
#: These go stale as providers retire models, which is why the UI can now
#: discover the live catalogue instead of trusting this map. Groq's previous
#: default (``llama-3.1-8b-instant``) moved to Enterprise-only, so a free key
#: got a model error on every run — the exact failure this avoids repeating.
DEFAULT_MODELS: dict[str, str] = {
    "groq": "openai/gpt-oss-120b",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "ollama": "llama3.1",
    "custom": "",
}

#: Default API roots, used for model discovery and as a fallback base URL.
DEFAULT_BASE_URLS: dict[str, str] = {
    "groq": "https://api.groq.com/openai/v1",
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434/v1",
}

#: Providers whose catalogue is served as OpenAI's ``GET /models`` shape.
OPENAI_COMPATIBLE: frozenset[str] = frozenset({"groq", "openai", "ollama", "custom"})

#: Providers that require a credential. Ollama runs locally and does not.
KEYLESS_PROVIDERS: frozenset[str] = frozenset({"ollama"})

#: Providers that cannot work without a user-supplied base URL.
REQUIRES_BASE_URL: frozenset[str] = frozenset({"custom"})


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"

    @property
    def is_terminal(self) -> bool:
        return self in {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
            RunStatus.TIMED_OUT,
        }


class RunTrigger(StrEnum):
    """What produced a run. Useful for cost attribution."""

    PIPELINE = "pipeline"
    TEAM = "team"
    RETRY = "retry"


class AgentKind(StrEnum):
    BUILTIN = "builtin"
    CUSTOM = "custom"


class EventType(StrEnum):
    RUN_QUEUED = "run.queued"
    RUN_STARTED = "run.started"
    RUN_SUCCEEDED = "run.succeeded"
    RUN_FAILED = "run.failed"
    RUN_CANCELLED = "run.cancelled"
    RUN_TIMED_OUT = "run.timed_out"

    AGENT_STARTED = "agent.started"
    AGENT_PROGRESS = "agent.progress"
    AGENT_COMPLETED = "agent.completed"
    AGENT_FAILED = "agent.failed"
    AGENT_MESSAGE = "agent.message"

    TOOL_STARTED = "tool.started"
    TOOL_COMPLETED = "tool.completed"

    SOURCE_ADDED = "source.added"
    CLAIM_REGISTERED = "claim.registered"
    REPORT_READY = "report.ready"

    BLACKBOARD_WRITE = "blackboard.write"
    LOG = "log"


class EventLevel(StrEnum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    SUCCESS = "success"


#: Canonical order of the built-in pipeline. Drives the UI timeline.
PIPELINE_ORDER: tuple[str, ...] = (
    "researcher",
    "web_searcher",
    "analyst",
    "summarizer",
)

BUILTIN_AGENT_SLUGS: tuple[str, ...] = PIPELINE_ORDER
