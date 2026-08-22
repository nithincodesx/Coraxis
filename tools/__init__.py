"""
Tools package — search, fetch, and citation tracking.
"""

from .search import (
    DuckDuckGoSearchTool,
    PageFetchTool,
    SearchResult,
    FetchedPage,
    make_search_tool,
    make_fetch_tool,
    search_and_fetch,
)
from .citations import (
    CitationTracker,
    CitationEntry,
    ClaimEntry,
)
from .crew_tools import (
    DuckDuckGoSearchToolWrapper,
    FetchPageToolWrapper,
    RecallMemoryToolWrapper,
    RegisterClaimTool,
    get_search_tool,
    get_fetch_tool,
    get_recall_tool,
    make_citation_aware_search_tool,
    make_citation_aware_fetch_tool,
    make_register_claim_tool,
)

from .aas_tools import (
    AASCatalogTool,
    AASStackValidatorTool,
    get_aas_catalog_tool,
    get_aas_stack_tool,
)

__all__ = [
    "DuckDuckGoSearchTool",
    "PageFetchTool",
    "SearchResult",
    "FetchedPage",
    "make_search_tool",
    "make_fetch_tool",
    "search_and_fetch",
    "CitationTracker",
    "CitationEntry",
    "ClaimEntry",
    "DuckDuckGoSearchToolWrapper",
    "FetchPageToolWrapper",
    "RecallMemoryToolWrapper",
    "RegisterClaimTool",
    "get_search_tool",
    "get_fetch_tool",
    "get_recall_tool",
    "make_citation_aware_search_tool",
    "make_citation_aware_fetch_tool",
    "make_register_claim_tool",
    "AASCatalogTool",
    "AASStackValidatorTool",
    "get_aas_catalog_tool",
    "get_aas_stack_tool",
]