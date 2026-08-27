"""
Search & Fetch Tools — DuckDuckGo search + page fetch/clean.
Returns structured results for CrewAI tools.
"""

import asyncio
import json
import time
from typing import Any, Optional
from dataclasses import dataclass, asdict
from urllib.parse import urlparse

import httpx
try:
    from duckduckgo_search import DDGS
except ImportError:
    class DDGS:
        def __init__(self, *args, **kwargs): pass
        def text(self, *args, **kwargs): return []

try:
    from trafilatura import fetch_url, extract
except ImportError:
    fetch_url = lambda *args, **kwargs: None
    extract = lambda *args, **kwargs: ""

try:
    from readability import Document
    READABILITY_AVAILABLE = True
except ImportError:
    READABILITY_AVAILABLE = False


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    source: str = "duckduckgo"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FetchedPage:
    url: str
    title: str
    text: str
    word_count: int
    fetch_time: float
    success: bool
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DuckDuckGoSearchTool:
    """
    DuckDuckGo search wrapper with rate-limit handling.
    Usage: tool = DuckDuckGoSearchTool(); results = tool.run("query", max_results=10)
    """

    def __init__(
        self,
        max_results: int = 10,
        region: str = "wt-wt",
        safesearch: str = "moderate",
        timeout: int = 15,
    ):
        self.max_results = max_results
        self.region = region
        self.safesearch = safesearch
        self.timeout = timeout
        self._ddgs = DDGS()

    def run(self, query: str, max_results: Optional[int] = None) -> list[SearchResult]:
        """Synchronous search."""
        return asyncio.run(self.arun(query, max_results))

    async def arun(self, query: str, max_results: Optional[int] = None) -> list[SearchResult]:
        """Async search with query validation and retry logic."""
        query = query.strip()
        if not query:
            return []
        max_r = max_results or self.max_results
        results: list[SearchResult] = []

        for attempt in range(3):
            try:
                raw_results = self._ddgs.text(
                    query,
                    region=self.region,
                    safesearch=self.safesearch,
                    max_results=max_r,
                )
                for r in raw_results:
                    results.append(SearchResult(
                        title=r.get("title", ""),
                        url=r.get("href", ""),
                        snippet=r.get("body", ""),
                    ))
                return results[:max_r]
            except Exception as e:
                if attempt == 2:
                    # Return empty on final failure
                    return []
                await asyncio.sleep(1.5 * (attempt + 1))

        return results

    def search_multiple(self, queries: list[str], max_per_query: int = 5) -> dict[str, list[SearchResult]]:
        """Run multiple searches in parallel."""
        async def _search_all():
            tasks = [self.arun(q, max_per_query) for q in queries]
            return await asyncio.gather(*tasks)

        all_results = asyncio.run(_search_all())
        return dict(zip(queries, all_results))


class PageFetchTool:
    """
    Fetch and clean web page content.
    Uses trafilatura (preferred) with readability fallback.
    """

    def __init__(
        self,
        timeout: int = 20,
        max_retries: int = 2,
        min_word_count: int = 100,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_word_count = min_word_count
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self._client.aclose()

    def run(self, url: str) -> FetchedPage:
        """Synchronous fetch."""
        return asyncio.run(self.arun(url))

    async def arun(self, url: str) -> FetchedPage:
        """Async fetch with retries."""
        start = time.time()
        last_error = ""

        for attempt in range(self.max_retries + 1):
            try:
                # Try trafilatura first (best extraction)
                downloaded = fetch_url(url, no_ssl=True)
                if downloaded:
                    text = extract(
                        downloaded,
                        include_comments=False,
                        include_tables=False,
                        include_formatting=False,
                        output_format="txt",
                    )
                    if text and len(text.split()) >= self.min_word_count:
                        title = self._extract_title(downloaded) or urlparse(url).netloc
                        return FetchedPage(
                            url=url,
                            title=title,
                            text=text.strip(),
                            word_count=len(text.split()),
                            fetch_time=time.time() - start,
                            success=True,
                        )

                # Fallback: readability-lxml
                if READABILITY_AVAILABLE:
                    resp = await self._client.get(url)
                    resp.raise_for_status()
                    doc = Document(resp.text)
                    text = doc.summary()
                    # Simple HTML strip
                    import re
                    text = re.sub(r"<[^>]+>", " ", text)
                    text = re.sub(r"\s+", " ", text).strip()
                    if len(text.split()) >= self.min_word_count:
                        return FetchedPage(
                            url=url,
                            title=doc.title() or urlparse(url).netloc,
                            text=text,
                            word_count=len(text.split()),
                            fetch_time=time.time() - start,
                            success=True,
                        )

                last_error = "Content too short or extraction failed"

            except httpx.TimeoutException:
                last_error = f"Timeout after {self.timeout}s"
            except httpx.HTTPStatusError as e:
                last_error = f"HTTP {e.response.status_code}"
            except Exception as e:
                last_error = str(e)[:200]

            if attempt < self.max_retries:
                await asyncio.sleep(1.0 * (attempt + 1))

        return FetchedPage(
            url=url,
            title="",
            text="",
            word_count=0,
            fetch_time=time.time() - start,
            success=False,
            error=last_error,
        )

    def _extract_title(self, html: str) -> Optional[str]:
        """Extract title from HTML."""
        import re
        match = re.search(r"<title[^>]*>([^<]+)</title>", html, re.IGNORECASE)
        return match.group(1).strip() if match else None

    async def fetch_multiple(self, urls: list[str]) -> list[FetchedPage]:
        """Fetch multiple URLs in parallel."""
        semaphore = asyncio.Semaphore(5)  # Limit concurrent connections

        async def _fetch_one(url: str) -> FetchedPage:
            async with semaphore:
                return await self.arun(url)

        tasks = [_fetch_one(u) for u in urls]
        return await asyncio.gather(*tasks)


# CrewAI Tool wrappers (for use in agents)
def make_search_tool(max_results: int = 10):
    """Create a CrewAI-compatible search tool function."""
    tool = DuckDuckGoSearchTool(max_results=max_results)

    def _search(query: str) -> str:
        results = tool.run(query)
        return json.dumps([r.to_dict() for r in results], ensure_ascii=False)

    _search.__name__ = "duckduckgo_search"
    _search.__doc__ = f"Search DuckDuckGo for '{query}' and return top {max_results} results as JSON."
    return _search


def make_fetch_tool():
    """Create a CrewAI-compatible fetch tool function."""
    fetcher = PageFetchTool()

    def _fetch(url: str) -> str:
        result = fetcher.run(url)
        return json.dumps(result.to_dict(), ensure_ascii=False)

    _fetch.__name__ = "fetch_page"
    _fetch.__doc__ = "Fetch and extract clean text content from a URL. Returns JSON with title, text, word_count."
    return _fetch


# Convenience functions for direct use
async def search_and_fetch(query: str, max_results: int = 8, max_fetch: int = 5) -> list[FetchedPage]:
    """Search then fetch top results."""
    search_tool = DuckDuckGoSearchTool(max_results=max_results)
    results = await search_tool.arun(query)

    urls = [r.url for r in results[:max_fetch] if r.url]
    if not urls:
        return []

    async with PageFetchTool() as fetcher:
        return await fetcher.fetch_multiple(urls)