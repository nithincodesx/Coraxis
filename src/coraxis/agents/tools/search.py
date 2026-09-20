"""Web search.

The upstream DuckDuckGo client is synchronous. Rather than wrapping it in
``asyncio.run`` — which raises the moment it is called from inside a running
event loop — it is dispatched to a worker thread via :func:`asyncio.to_thread`.
That keeps the loop free and is honest about what the library actually is.
"""

from __future__ import annotations

import asyncio
import contextlib
import random
from dataclasses import dataclass
from typing import Any

from coraxis.core.logging import get_logger

logger = get_logger("search")

#: Backoff between attempts, in seconds.
_BACKOFF_BASE = 1.5


@dataclass(frozen=True, slots=True)
class SearchResult:
    """One search hit."""

    title: str
    url: str
    snippet: str
    rank: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "snippet": self.snippet,
            "rank": self.rank,
        }


class SearchClient:
    """Rate-limit-aware DuckDuckGo search."""

    def __init__(
        self,
        *,
        max_results: int = 8,
        region: str = "wt-wt",
        safesearch: str = "moderate",
        timeout: float = 15.0,
        max_attempts: int = 3,
    ) -> None:
        self.max_results = max_results
        self.region = region
        self.safesearch = safesearch
        self.timeout = timeout
        self.max_attempts = max(1, max_attempts)

    async def search(self, query: str, max_results: int | None = None) -> list[SearchResult]:
        """Search for a query, returning an empty list rather than raising.

        A failed sub-query should degrade the report, not abort the run — the
        other sub-questions are still worth searching.
        """
        query = (query or "").strip()
        if not query:
            return []

        limit = max_results or self.max_results

        for attempt in range(self.max_attempts):
            try:
                raw = await asyncio.to_thread(self._blocking_search, query, limit)
                results = [
                    SearchResult(
                        title=str(item.get("title", "")).strip(),
                        url=str(item.get("href", "")).strip(),
                        snippet=str(item.get("body", "")).strip(),
                        rank=index,
                    )
                    for index, item in enumerate(raw)
                    if item.get("href")
                ]
                logger.debug("search ok", extra={"query": query[:80], "results": len(results)})
                return results[:limit]

            except Exception as exc:  # noqa: BLE001 - upstream raises many types
                is_last = attempt == self.max_attempts - 1
                logger.warning(
                    "search attempt %d/%d failed: %s",
                    attempt + 1,
                    self.max_attempts,
                    exc,
                    extra={"query": query[:80], "final": is_last},
                )
                if is_last:
                    return []
                # Exponential backoff with jitter, so parallel sub-queries do
                # not retry in lockstep and trip the rate limiter together.
                delay = _BACKOFF_BASE * (2**attempt) + random.uniform(0, 0.75)
                await asyncio.sleep(delay)

        return []

    async def search_many(
        self,
        queries: list[str],
        *,
        max_per_query: int | None = None,
        concurrency: int = 4,
    ) -> dict[str, list[SearchResult]]:
        """Search several queries with bounded concurrency.

        Bounded on purpose: firing fifteen searches at once is the fastest way
        to get rate-limited by DuckDuckGo and end up with nothing.
        """
        semaphore = asyncio.Semaphore(max(1, concurrency))

        async def _one(query: str) -> tuple[str, list[SearchResult]]:
            async with semaphore:
                return query, await self.search(query, max_per_query)

        pairs = await asyncio.gather(*(_one(query) for query in queries))
        return dict(pairs)

    def _blocking_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        """Run the synchronous client. Called on a worker thread."""
        from duckduckgo_search import DDGS

        # DDGS declares `timeout: int | None`; our setting is a float so it can
        # express sub-second budgets, which the library would reject.
        client = DDGS(timeout=int(self.timeout))
        try:
            return list(
                client.text(
                    query,
                    region=self.region,
                    safesearch=self.safesearch,
                    max_results=limit,
                )
            )
        finally:
            close = getattr(client, "close", None)
            if callable(close):
                with contextlib.suppress(Exception):  # best-effort cleanup
                    close()
