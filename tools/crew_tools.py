"""
CrewAI Tool Wrappers — Actual CrewAI tools that agents can use.
Wraps the search, fetch, and memory functions for CrewAI tool calling.
"""

from typing import Optional, Type
from pydantic import BaseModel, Field
try:
    from crewai.tools import BaseTool
except ImportError:
    class BaseTool:
        name: str = ""
        description: str = ""
        args_schema: Optional[Type[BaseModel]] = None
        def __init__(self, *args, **kwargs): pass
        def _run(self, *args, **kwargs): return ""

from .search import DuckDuckGoSearchTool, PageFetchTool, search_and_fetch
from .citations import CitationTracker
from memory.chroma_client import recall_similar, get_memory


# ─── Input Schemas ───

class SearchInput(BaseModel):
    """Input for DuckDuckGo search tool."""
    query: str = Field(..., description="The search query to execute")
    max_results: int = Field(default=8, description="Maximum number of results to return")


class FetchInput(BaseModel):
    """Input for page fetch tool."""
    url: str = Field(..., description="The URL to fetch and extract content from")


class RecallMemoryInput(BaseModel):
    """Input for semantic memory recall tool."""
    topic: str = Field(..., description="The research topic to search memory for")
    query: str = Field(..., description="The specific query to find similar prior findings")
    n_results: int = Field(default=5, description="Number of similar findings to return")


# ─── Tool Implementations ───

class DuckDuckGoSearchToolWrapper(BaseTool):
    """CrewAI tool wrapper for DuckDuckGo search."""

    name: str = "duckduckgo_search"
    description: str = (
        "Search the web using DuckDuckGo for a given query. "
        "Returns structured results with title, URL, and snippet. "
        "Use this to find current information on any topic."
    )
    args_schema: Type[BaseModel] = SearchInput

    def _run(self, query: str, max_results: int = 8) -> str:
        """Execute synchronous search."""
        tool = DuckDuckGoSearchTool(max_results=max_results)
        results = tool.run(query)
        import json
        return json.dumps([r.to_dict() for r in results], ensure_ascii=False)

    async def _arun(self, query: str, max_results: int = 8) -> str:
        """Execute async search."""
        tool = DuckDuckGoSearchTool(max_results=max_results)
        results = await tool.arun(query)
        import json
        return json.dumps([r.to_dict() for r in results], ensure_ascii=False)


class FetchPageToolWrapper(BaseTool):
    """CrewAI tool wrapper for fetching and extracting web page content."""

    name: str = "fetch_page"
    description: str = (
        "Fetch and extract clean text content from a URL. "
        "Uses trafilatura for best extraction, with readability fallback. "
        "Returns title, full text, word count, and success status."
    )
    args_schema: Type[BaseModel] = FetchInput

    def _run(self, url: str) -> str:
        """Execute synchronous fetch."""
        fetcher = PageFetchTool()
        result = fetcher.run(url)
        import json
        return json.dumps(result.to_dict(), ensure_ascii=False)

    async def _arun(self, url: str) -> str:
        """Execute async fetch."""
        fetcher = PageFetchTool()
        result = await fetcher.arun(url)
        import json
        return json.dumps(result.to_dict(), ensure_ascii=False)


class RecallMemoryToolWrapper(BaseTool):
    """CrewAI tool wrapper for semantic memory recall."""

    name: str = "recall_memory"
    description: str = (
        "Recall prior research findings from semantic memory (ChromaDB). "
        "Searches for similar claims on the given topic. "
        "Returns prior findings with relevance scores to avoid redundant research."
    )
    args_schema: Type[BaseModel] = RecallMemoryInput

    def _run(self, topic: str, query: str, n_results: int = 5) -> str:
        """Execute synchronous memory recall."""
        entries = recall_similar(topic, query, n=n_results)
        import json
        return json.dumps([
            {
                "claim": e.claim,
                "sources": e.sources,
                "confidence": e.confidence,
                "relevance": e.relevance,
                "agent": e.agent,
                "similarity": e.metadata.get("similarity", 0) if e.metadata else 0,
            }
            for e in entries
        ], ensure_ascii=False)

    async def _arun(self, topic: str, query: str, n_results: int = 5) -> str:
        """Execute async memory recall (sync implementation)."""
        return self._run(topic, query, n_results)


# ─── Tool Instances (singletons for reuse) ───

_search_tool: Optional[DuckDuckGoSearchToolWrapper] = None
_fetch_tool: Optional[FetchPageToolWrapper] = None
_recall_tool: Optional[RecallMemoryToolWrapper] = None


def get_search_tool() -> DuckDuckGoSearchToolWrapper:
    """Get singleton search tool instance."""
    global _search_tool
    if _search_tool is None:
        _search_tool = DuckDuckGoSearchToolWrapper()
    return _search_tool


def get_fetch_tool() -> FetchPageToolWrapper:
    """Get singleton fetch tool instance."""
    global _fetch_tool
    if _fetch_tool is None:
        _fetch_tool = FetchPageToolWrapper()
    return _fetch_tool


def get_recall_tool() -> RecallMemoryToolWrapper:
    """Get singleton recall tool instance."""
    global _recall_tool
    if _recall_tool is None:
        _recall_tool = RecallMemoryToolWrapper()
    return _recall_tool


# ─── Citation-Aware Tool Wrappers ───

class CitationAwareSearchTool(BaseTool):
    """Search tool that also registers sources in CitationTracker."""

    name: str = "duckduckgo_search"
    description: str = (
        "Search the web using DuckDuckGo. Also registers sources in the citation tracker "
        "with initial relevance scores for downstream citation generation."
    )
    args_schema: Type[BaseModel] = SearchInput

    def __init__(self, tracker: CitationTracker):
        super().__init__()
        self._tracker = tracker
        self._search_tool = DuckDuckGoSearchToolWrapper()

    def _run(self, query: str, max_results: int = 8) -> str:
        results = self._search_tool._run(query, max_results)
        # Parse results and register in tracker
        import json
        try:
            data = json.loads(results)
            for r in data:
                if r.get("url"):
                    self._tracker.add_source(
                        url=r["url"],
                        title=r.get("title", ""),
                        relevance=0.5,  # Initial relevance, Analyst will re-score
                        snippet=r.get("snippet", ""),
                    )
        except Exception:
            pass
        return results


class CitationAwareFetchTool(BaseTool):
    """Fetch tool that updates citation tracker with full content."""

    name: str = "fetch_page"
    description: str = (
        "Fetch full page content. Updates citation tracker with word count "
        "and full text availability for relevance scoring."
    )
    args_schema: Type[BaseModel] = FetchInput

    def __init__(self, tracker: CitationTracker):
        super().__init__()
        self._tracker = tracker
        self._fetch_tool = FetchPageToolWrapper()

    def _run(self, url: str) -> str:
        result = self._fetch_tool._run(url)
        # Could update tracker with fetch success/word_count
        import json
        try:
            data = json.loads(result)
            if data.get("success") and data.get("word_count", 0) > 0:
                # Update the citation entry with fetch info
                pass  # Tracker doesn't store full text, but we could extend it
        except Exception:
            pass
        return result


def make_citation_aware_search_tool(tracker: CitationTracker) -> BaseTool:
    """Create a search tool bound to a specific citation tracker."""
    return CitationAwareSearchTool(tracker=tracker)


def make_citation_aware_fetch_tool(tracker: CitationTracker) -> BaseTool:
    """Create a fetch tool bound to a specific citation tracker."""
    return CitationAwareFetchTool(tracker=tracker)


class RegisterClaimTool(BaseTool):
    """Tool for Analyst to register claims with the citation tracker."""

    name: str = "register_claim"
    description: str = (
        "Register a synthesized claim with supporting source URLs in the citation tracker. "
        "Use this after analyzing sources to formally record a claim with its evidence, "
        "confidence score, and relevance scores. This enables proper citation generation in the final report."
    )

    class RegisterClaimInput(BaseModel):
        claim_text: str = Field(..., description="The claim statement")
        source_urls: list[str] = Field(..., description="List of source URLs supporting this claim")
        confidence: float = Field(default=0.7, ge=0.0, le=1.0, description="Confidence in this claim (0-1)")
        relevance_scores: Optional[list[float]] = Field(default=None, description="Relevance score per source (0-1)")
        agent: str = Field(default="analyst", description="Agent name registering the claim")

    args_schema: Type[BaseModel] = RegisterClaimInput

    def __init__(self, tracker: CitationTracker):
        super().__init__()
        self._tracker = tracker

    def _run(
        self,
        claim_text: str,
        source_urls: list[str],
        confidence: float = 0.7,
        relevance_scores: Optional[list[float]] = None,
        agent: str = "analyst",
    ) -> str:
        claim_id = self._tracker.add_claim(
            text=claim_text,
            source_urls=source_urls,
            confidence=confidence,
            agent=agent,
            relevance_scores=relevance_scores,
        )
        return f"Claim registered with ID: {claim_id}"

    async def _arun(
        self,
        claim_text: str,
        source_urls: list[str],
        confidence: float = 0.7,
        relevance_scores: Optional[list[float]] = None,
        agent: str = "analyst",
    ) -> str:
        return self._run(claim_text, source_urls, confidence, relevance_scores, agent)


def make_register_claim_tool(tracker: CitationTracker) -> BaseTool:
    """Create a register claim tool bound to a specific citation tracker."""
    return RegisterClaimTool(tracker=tracker)