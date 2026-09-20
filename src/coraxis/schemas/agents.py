"""Agent definition and per-agent LLM settings schemas."""

from __future__ import annotations

from pydantic import Field, field_validator

from coraxis.db.enums import AgentKind, ProviderName
from coraxis.schemas.common import RequestModel, ResponseModel, UTCDatetime

SLUG_PATTERN = r"^[a-z][a-z0-9_]{1,63}$"


class AgentLLMSettingsOut(ResponseModel):
    """How an agent is configured to run for the requesting user."""

    provider: ProviderName
    model: str = ""
    temperature: float
    max_tokens: int
    base_url: str = ""


class AgentLLMSettingsIn(RequestModel):
    provider: ProviderName = "groq"
    model: str = Field(default="", max_length=120)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=64, le=200_000)
    base_url: str = Field(default="", max_length=255)


class AgentOut(ResponseModel):
    """An agent as exposed over the API.

    Carries no credential material — the provider and model are described, the
    key that would be used is not.
    """

    id: str
    slug: str
    name: str
    role: str
    goal: str
    backstory: str
    kind: AgentKind
    tools: list[str]
    position: int
    is_builtin: bool
    llm: AgentLLMSettingsOut
    created_at: UTCDatetime
    updated_at: UTCDatetime


class AgentCreate(RequestModel):
    """Create a custom agent, or update one you already own."""

    slug: str = Field(pattern=SLUG_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    role: str = Field(default="", max_length=200)
    goal: str = Field(default="", max_length=4000)
    backstory: str = Field(default="", max_length=8000)
    tools: list[str] = Field(default_factory=list, max_length=20)
    llm: AgentLLMSettingsIn = Field(default_factory=AgentLLMSettingsIn)

    @field_validator("tools")
    @classmethod
    def _unique_tools(cls, value: list[str]) -> list[str]:
        """De-duplicate while preserving order — tool order affects prompts."""
        seen: set[str] = set()
        result: list[str] = []
        for tool in value:
            if tool not in seen:
                seen.add(tool)
                result.append(tool)
        return result


class AgentUpdate(RequestModel):
    """Partial update. Every field is optional."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    role: str | None = Field(default=None, max_length=200)
    goal: str | None = Field(default=None, max_length=4000)
    backstory: str | None = Field(default=None, max_length=8000)
    tools: list[str] | None = Field(default=None, max_length=20)
    llm: AgentLLMSettingsIn | None = None


class ToolOut(ResponseModel):
    """A tool an agent may be granted."""

    id: str
    label: str
    description: str
    requires_tracker: bool = False


class AgentCatalog(ResponseModel):
    """Everything needed to render the agent builder."""

    agents: list[AgentOut]
    tools: list[ToolOut]
