"""
Agent Definitions — Four CrewAI agents with distinct roles, each bound to its own LLM.
Researcher → Web Searcher → Analyst → Summarizer (sequential chain).
"""

from typing import Optional, List, Dict, Any
try:
    from crewai import Agent
except ImportError:
    class Agent:
        def __init__(self, *args, **kwargs):
            self.role = kwargs.get("role", "")
            self.goal = kwargs.get("goal", "")
from pydantic import BaseModel, Field

from utils.llm_factory import create_llm, get_available_providers
from tools.crew_tools import (
    get_search_tool,
    get_fetch_tool,
    get_recall_tool,
    make_citation_aware_search_tool,
    make_citation_aware_fetch_tool,
)
from tools.citations import CitationTracker
from tools.aas_tools import get_aas_catalog_tool


def _create_researcher_tools(tracker: Optional[CitationTracker] = None) -> List[Any]:
    """Create tools for the Researcher agent with optional citation tracking."""
    if tracker:
        return [
            make_citation_aware_search_tool(tracker),
            get_recall_tool(),
            get_aas_catalog_tool(),
        ]
    return [
        get_search_tool(),
        get_recall_tool(),
        get_aas_catalog_tool(),
    ]


def _create_web_searcher_tools(tracker: Optional[CitationTracker] = None):
    """Create tools for the Web Searcher agent."""
    if tracker:
        return [
            make_citation_aware_search_tool(tracker),
            make_citation_aware_fetch_tool(tracker),
        ]
    return [
        get_search_tool(),
        get_fetch_tool(),
    ]


def _create_analyst_tools(tracker: Optional[CitationTracker] = None):
    """Create tools for the Analyst agent."""
    if tracker:
        from tools.crew_tools import make_register_claim_tool
        return [
            get_recall_tool(),
            make_register_claim_tool(tracker),
        ]
    return [
        get_recall_tool(),
    ]


# Agent role definitions (tools will be injected at creation time)
AGENT_CONFIGS = {
    "researcher": {
        "role": "Senior Research Analyst",
        "goal": (
            "Decompose the user's research query into specific, searchable sub-questions. "
            "Identify key themes, entities, and angles that need investigation. "
            "Recall relevant prior findings from semantic memory to avoid redundant search."
        ),
        "backstory": (
            "You are a veteran research analyst with 15 years of experience in intelligence gathering "
            "and competitive analysis. You excel at breaking down complex topics into precise, "
            "answerable questions. You never start from zero — you always check what's already known "
            "before launching new searches. Your sub-questions are surgical, not scattershot."
        ),
    },
    "web_searcher": {
        "role": "Web Search Specialist",
        "goal": (
            "Execute targeted web searches for each sub-question. Fetch and extract clean, "
            "relevant content from top results. Return structured findings with URLs, titles, "
            "snippets, and full extracted text for downstream analysis."
        ),
        "backstory": (
            "You are a web search specialist who knows how to coax the best results from search engines. "
            "You don't just grab the first page — you evaluate result quality, fetch full content, "
            "and extract only the signal. You handle rate limits gracefully and always return "
            "structured, citation-ready data."
        ),
    },
    "analyst": {
        "role": "Synthesis Analyst",
        "goal": (
            "Cross-reference all gathered findings. Score each source's relevance (0–100%). "
            "Detect contradictions and consensus. Synthesize claims with confidence scores. "
            "Produce a structured analysis with claims, supporting sources, relevance scores, "
            "and confidence levels for the report writer."
        ),
        "backstory": (
            "You are a synthesis analyst trained in intelligence analysis methodologies. "
            "You don't just summarize — you evaluate. You weigh source credibility, detect "
            "echo chambers, identify gaps, and assign calibrated confidence to every claim. "
            "Your output is a precise, structured brief that the report writer can trust."
        ),
    },
    "summarizer": {
        "role": "Report Writer",
        "goal": (
            "Produce a polished, structured markdown report with: executive summary, "
            "detailed findings sections, inline citations [^n], source appendix with relevance "
            "scores, and a confidence assessment. Write for a technical decision-maker audience."
        ),
        "backstory": (
            "You are a senior technical writer who translates analytic products into clear, "
            "actionable reports. You know that a report without citations is opinion, not intelligence. "
            "You structure for scannability: executive summary up front, evidence-backed findings, "
            "and a source appendix that lets readers verify every claim."
        ),
    },
}


class AgentFactory:
    """Creates CrewAI Agent instances with per-agent LLM binding."""

    def __init__(
        self,
        use_global_key: bool = False,
        global_key: str = "",
        tracker: Optional[CitationTracker] = None,
    ):
        self.use_global_key = use_global_key
        self.global_key = global_key
        self.tracker = tracker
        self._agents: dict[str, Agent] = {}

    def create_all(self) -> dict[str, Agent]:
        """Create all four agents."""
        for name in ["researcher", "web_searcher", "analyst", "summarizer"]:
            self._agents[name] = self.create(name)
        return self._agents

    def create(self, name: str) -> Agent:
        """Create a single agent by name with appropriate tools."""
        if name not in AGENT_CONFIGS:
            raise ValueError(f"Unknown agent: {name}")

        config = AGENT_CONFIGS[name]
        llm = create_llm(name, use_global_key=self.use_global_key, global_key=self.global_key)

        # Get tools for this agent
        tools = self._get_tools_for_agent(name)

        agent = Agent(
            role=config["role"],
            goal=config["goal"],
            backstory=config["backstory"],
            llm=llm,
            verbose=True,
            allow_delegation=False,
            max_iter=5,
            max_retry_limit=2,
            respect_context_window=True,
            tools=tools,
        )

        return agent

    def _get_tools_for_agent(self, name: str):
        """Get the appropriate tools for an agent."""
        if name == "researcher":
            return _create_researcher_tools(self.tracker)
        elif name == "web_searcher":
            return _create_web_searcher_tools(self.tracker)
        elif name == "analyst":
            return _create_analyst_tools(self.tracker)
        elif name == "summarizer":
            return []
        return []

    def get(self, name: str) -> Optional[Agent]:
        """Get already-created agent."""
        return self._agents.get(name)

    @property
    def researcher(self) -> Agent:
        return self._agents["researcher"]

    @property
    def web_searcher(self) -> Agent:
        return self._agents["web_searcher"]

    @property
    def analyst(self) -> Agent:
        return self._agents["analyst"]

    @property
    def summarizer(self) -> Agent:
        return self._agents["summarizer"]


def create_agents(
    use_global_key: bool = False,
    global_key: str = "",
) -> AgentFactory:
    """Convenience function to create all agents."""
    factory = AgentFactory(use_global_key=use_global_key, global_key=global_key)
    factory.create_all()
    return factory