"""Team composition and workflow schemas."""

from __future__ import annotations

from pydantic import Field, field_validator

from coraxis.schemas.common import RequestModel, ResponseModel, UTCDatetime


class TeamStepIn(RequestModel):
    """One step in a team's workflow."""

    agent_slug: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=4000)
    expected_output: str = Field(default="", max_length=2000)


class TeamStepOut(ResponseModel):
    position: int
    agent_slug: str
    description: str
    expected_output: str


class TeamCreate(RequestModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    agent_slugs: list[str] = Field(min_length=1, max_length=12)
    coordinator_slug: str | None = Field(default=None, max_length=64)
    coordinator_instructions: str = Field(default="", max_length=4000)
    steps: list[TeamStepIn] = Field(default_factory=list, max_length=24)

    @field_validator("agent_slugs")
    @classmethod
    def _dedupe(cls, value: list[str]) -> list[str]:
        """A team is a set of agents in a meaningful order."""
        seen: set[str] = set()
        ordered: list[str] = []
        for slug in value:
            if slug not in seen:
                seen.add(slug)
                ordered.append(slug)
        return ordered


class TeamUpdate(RequestModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    agent_slugs: list[str] | None = Field(default=None, min_length=1, max_length=12)
    coordinator_slug: str | None = Field(default=None, max_length=64)
    coordinator_instructions: str | None = Field(default=None, max_length=4000)
    steps: list[TeamStepIn] | None = Field(default=None, max_length=24)


class TeamOut(ResponseModel):
    id: str
    name: str
    description: str
    agent_slugs: list[str]
    coordinator_slug: str | None = None
    coordinator_instructions: str = ""
    steps: list[TeamStepOut] = Field(default_factory=list)
    created_at: UTCDatetime
    updated_at: UTCDatetime
