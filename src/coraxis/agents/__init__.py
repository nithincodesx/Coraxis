"""Agent domain: definitions, tools, tasks, and crew assembly.

Nothing in this package imports the database, the HTTP layer, or a service. A
crew is built from :class:`~coraxis.agents.crew.AgentSpec` objects and a
:class:`~coraxis.agents.context.ToolContext`, both of which are plain data. That
is what makes the pipeline testable without a server or a network.
"""

from __future__ import annotations

from coraxis.agents.citations import Citation, CitationTracker, Claim
from coraxis.agents.comms import AgentChannel, AgentMessage
from coraxis.agents.context import ToolContext
from coraxis.agents.crew import AgentSpec, build_agent, build_pipeline_crew, build_team_crew
from coraxis.agents.definitions import BUILTIN_AGENT_DEFINITIONS, PIPELINE_LABELS
from coraxis.agents.tasks import (
    AnalyzedFindings,
    FinalReport,
    FindingItem,
    RawFindings,
    ReportStats,
    SourceRef,
    SubQuestions,
)
from coraxis.agents.tasks import (
    Claim as AnalyzedClaim,
)
from coraxis.agents.tool_registry import ALWAYS_AVAILABLE, TOOL_REGISTRY, ToolSpec

__all__ = [
    "ALWAYS_AVAILABLE",
    "BUILTIN_AGENT_DEFINITIONS",
    "PIPELINE_LABELS",
    "TOOL_REGISTRY",
    "AgentChannel",
    "AgentMessage",
    "AgentSpec",
    "AnalyzedClaim",
    "AnalyzedFindings",
    "Citation",
    "CitationTracker",
    "Claim",
    "FinalReport",
    "FindingItem",
    "RawFindings",
    "ReportStats",
    "SourceRef",
    "SubQuestions",
    "ToolContext",
    "ToolSpec",
    "build_agent",
    "build_pipeline_crew",
    "build_team_crew",
]
