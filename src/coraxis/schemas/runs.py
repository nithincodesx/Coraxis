"""Run submission, status, and result schemas."""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from coraxis.db.enums import EventLevel, EventType, RunStatus, RunTrigger
from coraxis.schemas.common import RequestModel, ResponseModel, UTCDatetime

MAX_QUERY_LENGTH = 2000
MIN_QUERY_LENGTH = 3


class RunOptions(RequestModel):
    """Knobs captured at submission so a run can be replayed identically."""

    max_sources: int | None = Field(default=None, ge=1, le=50)
    max_fetch_per_query: int | None = Field(default=None, ge=1, le=20)
    include_memory: bool = True
    min_confidence: float = Field(default=0.3, ge=0.0, le=1.0)


class RunCreate(RequestModel):
    """Submit a research run."""

    query: str = Field(min_length=MIN_QUERY_LENGTH, max_length=MAX_QUERY_LENGTH)
    team_id: str | None = Field(
        default=None, description="Run a saved team instead of the default pipeline."
    )
    options: RunOptions = Field(default_factory=RunOptions)

    @model_validator(mode="after")
    def _query_must_be_meaningful(self) -> RunCreate:
        if len(self.query.split()) < 2:
            raise ValueError("Query must contain at least two words.")
        return self


class RunStats(ResponseModel):
    """Aggregate numbers describing a finished run."""

    total_sources: int = 0
    total_claims: int = 0
    avg_confidence: float = 0.0
    avg_relevance: float = 0.0
    agents_used: list[str] = Field(default_factory=list)
    models_used: dict[str, str] = Field(default_factory=dict)
    runtime_seconds: float = 0.0


class SourceOut(ResponseModel):
    id: str
    url: str
    title: str
    relevance: float
    relevance_pct: int = 0
    snippet: str = ""
    word_count: int = 0
    fetch_success: bool = False


class ClaimOut(ResponseModel):
    id: str
    claim_ref: str
    text: str
    confidence: float
    relevance: float
    agent: str
    source_urls: list[str] = Field(default_factory=list)


class RunEventOut(ResponseModel):
    """One entry in a run's timeline.

    ``seq`` is the resumption cursor: a client that reconnects with
    ``Last-Event-ID: <seq>`` receives only what it missed.
    """

    id: str
    seq: int
    type: EventType
    agent: str = ""
    level: EventLevel
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: UTCDatetime


class RunOut(ResponseModel):
    """Summary view — everything the run list needs, and no report body."""

    id: str
    query: str
    status: RunStatus
    trigger: RunTrigger
    team_id: str | None = None
    error: str = ""
    options: dict[str, Any] = Field(default_factory=dict)
    stats: RunStats = Field(default_factory=RunStats)
    executive_summary: str = ""
    key_findings: list[str] = Field(default_factory=list)
    source_count: int = 0
    claim_count: int = 0
    created_at: UTCDatetime
    started_at: UTCDatetime | None = None
    finished_at: UTCDatetime | None = None
    runtime_seconds: float = 0.0


class RunDetail(RunOut):
    """Full view, including the report and its evidence."""

    report_markdown: str = ""
    citations_markdown: str = ""
    sources: list[SourceOut] = Field(default_factory=list)
    claims: list[ClaimOut] = Field(default_factory=list)


class RunAccepted(ResponseModel):
    """Returned by the submit endpoint — 202, not 200."""

    run_id: str
    status: RunStatus
    stream_url: str = Field(description="SSE endpoint for live progress.")
    detail_url: str
