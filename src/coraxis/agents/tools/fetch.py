"""Page fetching and clean-text extraction.

Two defects in the previous implementation are fixed here:

1. Extraction used Trafilatura's ``fetch_url``, which is synchronous, from
   inside an ``async def``. That blocked the event loop for the entire network
   round-trip. The HTTP request is now made with the shared async client and
   only the CPU-bound parsing is offloaded to a thread.
2. The ``httpx.AsyncClient`` was constructed in ``__init__`` and only closed
   through an async context manager that callers never used, leaking a
   connection pool per instantiation. The client is now lazily created, reused,
   and explicitly closable.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import asdict, dataclass
from typing import Any

import httpx

from coraxis.core.logging import get_logger

logger = get_logger("fetch")

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)

#: Content types worth attempting to extract. Anything else (PDFs, images,
#: video) is skipped rather than downloaded and parsed for nothing.
_EXTRACTABLE = ("text/html", "application/xhtml", "text/plain")


@dataclass(slots=True)
class FetchedPage:
    """The result of fetching one URL."""

    url: str
    title: str = ""
    text: str = ""
    word_count: int = 0
    fetch_time: float = 0.0
    success: bool = False
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PageFetcher:
    """Async page fetcher with a reused connection pool.

    Use as an async context manager so the pool is closed deterministically::

        async with PageFetcher() as fetcher:
            page = await fetcher.fetch("https://example.com")
    """

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        max_retries: int = 2,
        min_word_count: int = 100,
        max_concurrency: int = 5,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.timeout = timeout
        self.max_retries = max(0, max_retries)
        self.min_word_count = min_word_count
        self.max_concurrency = max(1, max_concurrency)
        self.user_agent = user_agent
        self._client: httpx.AsyncClient | None = None

    # ── Lifecycle ────────────────────────────────────────────────────

    @property
    def client(self) -> httpx.AsyncClient:
        """The shared client, created on first use."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                },
                limits=httpx.Limits(max_connections=self.max_concurrency * 2),
            )
        return self._client

    async def aclose(self) -> None:
        """Close the connection pool. Safe to call more than once."""
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    async def __aenter__(self) -> PageFetcher:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    # ── Fetching ─────────────────────────────────────────────────────

    async def fetch(self, url: str) -> FetchedPage:
        """Fetch and extract one page.

        Returns a :class:`FetchedPage` with ``success=False`` on failure rather
        than raising — a dead link is a normal outcome of web research, and the
        pipeline should record it and continue.
        """
        started = time.perf_counter()
        url = (url or "").strip()
        if not url:
            return FetchedPage(url=url, error="Empty URL")

        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.get(url)
                response.raise_for_status()

                content_type = response.headers.get("content-type", "").lower()
                if content_type and not any(kind in content_type for kind in _EXTRACTABLE):
                    return FetchedPage(
                        url=str(response.url),
                        fetch_time=time.perf_counter() - started,
                        error=f"Unsupported content type: {content_type.split(';')[0]}",
                    )

                html = response.text
                title, text = await asyncio.to_thread(self._extract, html, url)

                if len(text.split()) < self.min_word_count:
                    last_error = (
                        f"Extracted only {len(text.split())} words (minimum {self.min_word_count})"
                    )
                else:
                    return FetchedPage(
                        url=str(response.url),
                        title=title,
                        text=text,
                        word_count=len(text.split()),
                        fetch_time=round(time.perf_counter() - started, 3),
                        success=True,
                    )

            except httpx.TimeoutException:
                last_error = f"Timed out after {self.timeout}s"
            except httpx.HTTPStatusError as exc:
                last_error = f"HTTP {exc.response.status_code}"
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            except Exception as exc:  # noqa: BLE001 - extraction can fail in many ways
                last_error = f"{type(exc).__name__}: {exc}"[:200]

            if attempt < self.max_retries:
                await asyncio.sleep(1.0 * (attempt + 1))

        logger.debug("fetch failed", extra={"url": url[:120], "error": last_error})
        return FetchedPage(
            url=url,
            fetch_time=round(time.perf_counter() - started, 3),
            error=last_error,
        )

    async def fetch_many(self, urls: list[str]) -> list[FetchedPage]:
        """Fetch several URLs with bounded concurrency, preserving input order."""
        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _one(target: str) -> FetchedPage:
            async with semaphore:
                return await self.fetch(target)

        return list(await asyncio.gather(*(_one(url) for url in urls)))

    # ── Extraction ───────────────────────────────────────────────────

    def _extract(self, html: str, url: str) -> tuple[str, str]:
        """Extract ``(title, text)``. Runs on a worker thread.

        Trafilatura is tried first because it produces the cleanest output;
        readability-lxml is the fallback for pages it declines.
        """
        title = self._extract_title(html)
        text = ""

        try:
            from trafilatura import extract

            text = (
                extract(
                    html,
                    url=url,
                    include_comments=False,
                    include_tables=False,
                    include_formatting=False,
                    output_format="txt",
                    favor_precision=True,
                )
                or ""
            )
        except Exception as exc:  # noqa: BLE001 - fall through to readability
            logger.debug("trafilatura extraction failed", extra={"error": str(exc)[:120]})

        if len(text.split()) < self.min_word_count:
            fallback = self._extract_readability(html)
            if len(fallback.split()) > len(text.split()):
                text = fallback

        if not title:
            title = _first_line(text)

        return title.strip(), _WHITESPACE_RE.sub(" ", text).strip()

    @staticmethod
    def _extract_title(html: str) -> str:
        match = _TITLE_RE.search(html)
        return _WHITESPACE_RE.sub(" ", match.group(1)).strip() if match else ""

    @staticmethod
    def _extract_readability(html: str) -> str:
        try:
            from readability import Document

            summary = Document(html).summary()
            return _WHITESPACE_RE.sub(" ", _TAG_RE.sub(" ", summary)).strip()
        except Exception:  # noqa: BLE001 - optional dependency, best effort
            return ""


def _first_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:200]
    return ""
