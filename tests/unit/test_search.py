"""Tests for Phase 02C Web Search and Source Intelligence.

Search and fetch are tested with fakes: no live network, no external search
service, no network access at all. SSRF protection is exercised by feeding
blocked URLs directly to the fetcher.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import pytest

from coraxis.agents.citations import CitationTracker
from coraxis.agents.context import ToolContext
from coraxis.agents.tools.fetch import (
    PageFetcher,
    _host_is_allowed,
    _url_is_fetchable,
)
from coraxis.agents.tools.search import SearchResult
from coraxis.agents.tools.source_utils import classify_source, normalize_url, same_document

# ─── URL normalization ─────────────────────────────────────────────────


def test_normalize_url_strips_tracking_params_and_fragment() -> None:
    assert normalize_url("https://Example.COM/page/") == "https://example.com/page"
    assert (
        normalize_url("https://example.com/page?utm_source=foo&utm_campaign=bar#section")
        == "https://example.com/page"
    )


def test_normalize_url_removes_default_ports_and_sorts_query() -> None:
    assert normalize_url("http://example.com:80/a") == "http://example.com/a"
    assert normalize_url("https://example.com:443/a") == "https://example.com/a"
    assert normalize_url("https://example.com/a?z=1&b=2") == "https://example.com/a?b=2&z=1"


def test_same_document_catches_equivalent_urls() -> None:
    assert same_document("https://Example.COM/page?utm_campaign=x", "https://example.com/page")
    assert not same_document("https://example.com/a", "https://example.com/b")


# ─── Source classification (heuristic) ─────────────────────────────────


def test_classify_source_primary() -> None:
    assert classify_source("https://www.cdc.gov/flu") == "primary"
    assert classify_source("https://www.whitehouse.gov/") == "primary"


def test_classify_source_academic() -> None:
    assert classify_source("https://arxiv.org/abs/2301.00001") == "academic"
    assert classify_source("https://mit.edu/") == "academic"


def test_classify_source_news() -> None:
    assert classify_source("https://www.reuters.com/world/") == "news"
    assert classify_source("https://www.bbc.com/news") == "news"


def test_classify_source_documentation_and_general() -> None:
    assert classify_source("https://example.com/docs/api/") == "official_documentation"
    assert classify_source("https://random-blog.example/post") == "general"


# ─── SSRF protection ───────────────────────────────────────────────────


def test_host_is_allowed_blocks_localhost() -> None:
    assert _host_is_allowed("localhost") is False
    assert _host_is_allowed("127.0.0.1") is False
    assert _host_is_allowed("::1") is False


def test_host_is_allowed_blocks_private_ranges() -> None:
    assert _host_is_allowed("10.0.0.5") is False
    assert _host_is_allowed("172.16.0.1") is False
    assert _host_is_allowed("192.168.1.10") is False
    assert _host_is_allowed("169.254.169.254") is False  # link-local / IMDS


def test_host_is_allowed_blocks_multicast_and_reserved() -> None:
    assert _host_is_allowed("224.0.0.1") is False
    assert _host_is_allowed("0.0.0.0") is False


def test_host_is_allowed_allows_public_hosts(monkeypatch: pytest.MonkeyPatch) -> None:
    # Stub DNS: this test must not depend on how the host running it resolves
    # example.com (some sandboxes/proxies resolve it to a benchmarking-range
    # address that the SSRF guard correctly treats as private).
    monkeypatch.setattr(
        "coraxis.agents.tools.fetch.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert _host_is_allowed("example.com") is True
    assert _host_is_allowed("example.org") is True


def test_url_is_fetchable_blocks_unsafe_schemes() -> None:
    assert _url_is_fetchable("ftp://example.com/file") is not None
    assert _url_is_fetchable("file:///etc/passwd") is not None
    assert _url_is_fetchable("javascript:alert(1)") is not None


def test_url_is_fetchable_blocks_bad_hosts() -> None:
    assert _url_is_fetchable("http://127.0.0.1/") is not None
    assert _url_is_fetchable("https://localhost/admin") is not None
    assert _url_is_fetchable("http://169.254.169.254/") is not None


def test_url_is_fetchable_allows_https(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "coraxis.agents.tools.fetch.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert _url_is_fetchable("https://example.com/page") is None


# ─── Fetcher rejects blocked URLs without network ──────────────────────


def test_fetcher_rejects_blocked_url_without_network() -> None:
    fetcher = PageFetcher(timeout=5.0)
    page = asyncio.run(fetcher.fetch("http://127.0.0.1/"))
    assert page.success is False
    assert page.error and "Blocked host" in page.error
    assert page.retrieved_at


def test_fetcher_rejects_private_ip_without_network() -> None:
    fetcher = PageFetcher(timeout=5.0)
    page = asyncio.run(fetcher.fetch("http://169.254.169.254/latest/meta-data/"))
    assert page.success is False
    assert "Blocked host" in page.error


# ─── CitationTracker normalization-based dedup ─────────────────────────


def test_tracker_dedupes_by_normalized_url() -> None:
    tracker = CitationTracker()
    a = tracker.add_source("https://example.com/page", title="A", relevance=0.5)
    b = tracker.add_source("https://example.com/page/", title="A again", relevance=0.9)
    c = tracker.add_source("HTTPS://EXAMPLE.COM/page?utm_source=x", title="A third", relevance=0.4)

    assert a == b == c, "equivalent URLs must share one citation"
    assert len(tracker) == 1
    assert tracker.citations[0].relevance == 0.9  # best relevance wins
    stats = tracker.stats()
    assert stats["discovered_sources"] == 3
    assert stats["duplicate_sources"] == 2


def test_tracker_duplicate_of_is_recorded() -> None:
    tracker = CitationTracker()
    canonical = tracker.add_source("https://example.com/page", title="Canon")
    duplicate = tracker.add_source("https://example.com/page/?utm_source=x", title="Dup")
    assert canonical == duplicate
    # The canonical citation keeps its own id; duplicate_of is empty on it.
    assert tracker.citations[0].duplicate_of == ""
    # A duplicate URL resolves to the canonical citation (provenance preserved).
    assert tracker.citation_for_url("https://example.com/page/?utm_source=x").id == canonical
    stats = tracker.stats()
    assert stats["discovered_sources"] == 2
    assert stats["duplicate_sources"] == 1


# ─── SearchTool classifies category and records discovery query ─────────


@dataclass
class _FakeSearch:
    """Fake SearchClient: returns canned results for any query."""

    results_by_query: dict[str, list[dict[str, Any]]]

    async def search(self, query: str, max_results: int | None = None):
        return [
            SearchResult(
                title=item["title"],
                url=item["url"],
                snippet=item.get("snippet", ""),
                rank=index,
            )
            for index, item in enumerate(self.results_by_query.get(query, []))
        ]


def test_search_tool_classifies_category_and_records_query() -> None:
    tracker = CitationTracker()
    fake_search = _FakeSearch(
        {
            "what is cdc guidance": [
                {"title": "CDC Guidance", "url": "https://www.cdc.gov/flu", "snippet": "guidance"}
            ]
        }
    )
    context = ToolContext(
        tracker=tracker,
        search=fake_search,  # type: ignore[arg-type]
        fetcher=None,  # type: ignore[arg-type]
        run_id="run-1",
        agent_slug="web_searcher",
    )

    from coraxis.agents.tools.crew_tools import SearchTool

    tool = SearchTool(context=context)
    result = asyncio.run(tool._arun(query="what is cdc guidance"))

    assert len(tracker) == 1
    citation = tracker.citations[0]
    assert citation.source_category == "primary"
    assert citation.discovery_query == "what is cdc guidance"

    payload = __import__("json").loads(result)
    assert payload["query"] == "what is cdc guidance"
    assert len(payload["results"]) == 1


@dataclass
class _FakeFetcher:
    """Fake fetcher returning a successful page."""

    async def fetch(self, url: str):
        from coraxis.agents.tools.fetch import FetchedPage

        return FetchedPage(
            url=url,
            title="Example Page",
            text="Some extracted content here about the topic.",
            word_count=9,
            fetch_time=0.5,
            success=True,
            retrieved_at="2026-11-10T00:00:00+00:00",
        )

    async def aclose(self) -> None:
        return None


def test_fetch_tool_records_category_and_retrieval_date() -> None:
    tracker = CitationTracker()
    context = ToolContext(
        tracker=tracker,
        search=None,  # type: ignore[arg-type]
        fetcher=_FakeFetcher(),  # type: ignore[arg-type]
        run_id="run-1",
        agent_slug="web_searcher",
    )

    from coraxis.agents.tools.crew_tools import FetchTool

    tool = FetchTool(context=context)
    result = asyncio.run(tool._arun(url="https://example.com/page"))

    payload = __import__("json").loads(result)
    assert payload["success"] is True
    assert len(tracker) == 1
    citation = tracker.citations[0]
    assert citation.source_category == "general"
    assert citation.retrieval_date == "2026-11-10T00:00:00+00:00"


# ─── SSRF security tests (mocked, no network) ──────────────────────────


class _FakeResponse:
    """Minimal httpx.Response stand-in for redirect tests."""

    def __init__(self, *, status_code: int, url: str, headers: dict | None = None) -> None:
        self.status_code = status_code
        self.url = url
        # httpx headers are case-insensitive; mirror that behaviour.
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}
        self.history: list = []
        self.is_redirect = 300 <= status_code < 400

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(f"HTTP {self.status_code}", request=None, response=self)


class _FakeAsyncClient:
    """Fake httpx.AsyncClient that returns canned responses."""

    def __init__(self, responses: dict[str, _FakeResponse]) -> None:
        self._responses = responses
        self._closed = False

    @property
    def is_closed(self) -> bool:
        return self._closed

    async def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        return self._responses.get(url, _FakeResponse(status_code=404, url=url))

    async def aclose(self) -> None:
        self._closed = True


async def _fetch_with_mocked_client(
    fetcher: PageFetcher,
    responses: dict[str, _FakeResponse],
    start_url: str = "https://example.com/",
) -> Any:
    """Run fetcher.fetch with a mocked httpx client."""
    client = _FakeAsyncClient(responses)
    fetcher._client = client  # bypass lazy creation
    return await fetcher.fetch(start_url)


def test_ipv4_mapped_ipv6_loopback_is_blocked() -> None:
    """IPv4-mapped IPv6 loopback (::ffff:127.0.0.1) must be blocked."""
    assert _host_is_allowed("::ffff:127.0.0.1") is False


def test_ipv4_mapped_ipv6_private_is_blocked() -> None:
    """IPv4-mapped IPv6 private address (::ffff:10.0.0.1) must be blocked."""
    assert _host_is_allowed("::ffff:10.0.0.1") is False


def test_port_whitelist_blocks_non_standard_port(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-standard ports (e.g. SSH 22) are blocked even on public hosts."""
    monkeypatch.setattr(
        "coraxis.agents.tools.fetch.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 22))],
    )
    assert _host_is_allowed("example.com", 22) is False


def test_port_whitelist_allows_standard_ports(monkeypatch: pytest.MonkeyPatch) -> None:
    """Standard web ports (443) are allowed on public hosts."""
    monkeypatch.setattr(
        "coraxis.agents.tools.fetch.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert _host_is_allowed("example.com", 443) is True


def test_credentials_in_url_are_blocked() -> None:
    """URLs with embedded user:password credentials are rejected."""
    assert _url_is_fetchable("http://user:pass@example.com/") is not None
    assert _url_is_fetchable("https://user:pass@internal.example.com/") is not None


def test_dns_rebinding_private_ip_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DNS resolves to a private IP, the host is blocked."""
    monkeypatch.setattr(
        "coraxis.agents.tools.fetch.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("10.0.0.1", 443))],
    )
    assert _host_is_allowed("evil.example.com") is False


def test_dns_rebinding_public_ip_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    """When DNS resolves to a public IP, the host is allowed."""
    monkeypatch.setattr(
        "coraxis.agents.tools.fetch.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    assert _host_is_allowed("example.com") is True


def test_redirect_to_private_ip_is_blocked_before_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A redirect to a private IP is blocked before the connection is made.

    The initial URL is public, but the redirect target (127.0.0.1) is
    validated against the SSRF allowlist before any second request.
    """
    fetcher = PageFetcher(timeout=5.0)

    start = _FakeResponse(
        status_code=302, url="https://example.com/", headers={"Location": "http://127.0.0.1/"}
    )
    target = _FakeResponse(status_code=200, url="http://127.0.0.1/")

    responses = {
        "https://example.com/": start,
        "http://127.0.0.1/": target,
    }

    page = asyncio.run(_fetch_with_mocked_client(fetcher, responses))
    assert page.success is False
    assert "Blocked host" in page.error or "127.0.0.1" in page.error


def test_redirect_chain_all_hops_validated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every hop in a redirect chain is validated, not just the final one."""
    fetcher = PageFetcher(timeout=5.0)

    hop1 = _FakeResponse(
        status_code=302,
        url="https://example.com/",
        headers={"Location": "https://internal.example.com/hop1"},
    )
    hop2 = _FakeResponse(
        status_code=302,
        url="https://internal.example.com/hop1",
        headers={"Location": "http://127.0.0.1/secret"},
    )
    final = _FakeResponse(status_code=200, url="http://127.0.0.1/secret")

    responses = {
        "https://example.com/": hop1,
        "https://internal.example.com/hop1": hop2,
        "http://127.0.0.1/secret": final,
    }

    page = asyncio.run(_fetch_with_mocked_client(fetcher, responses))
    assert page.success is False
    assert "Blocked host" in page.error


def test_max_redirects_enforced(monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect chains longer than _MAX_REDIRECTS are rejected.

    Uses a redirect loop (A → B → A → ...) so the chain never terminates
    naturally, forcing the redirect count limit to kick in.
    """
    monkeypatch.setattr(
        "coraxis.agents.tools.fetch.socket.getaddrinfo",
        lambda *a, **k: [(2, 1, 6, "", ("93.184.216.34", 443))],
    )
    fetcher = PageFetcher(timeout=5.0)

    responses = {
        "https://example.com/": _FakeResponse(
            status_code=302,
            url="https://example.com/",
            headers={"Location": "https://example.com/redirect/"},
        ),
        "https://example.com/redirect/": _FakeResponse(
            status_code=302,
            url="https://example.com/redirect/",
            headers={"Location": "https://example.com/"},
        ),
    }

    page = asyncio.run(_fetch_with_mocked_client(fetcher, responses))
    assert page.success is False
    assert "Too many redirects" in page.error


def test_httpx_client_disables_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The httpx client sets trust_env=False to block proxy-based SSRF bypass."""
    # Set a proxy env var to confirm it is ignored.
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.internal:3128")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.internal:3128")

    fetcher = PageFetcher(timeout=5.0)
    client = fetcher.client  # force creation
    assert client._trust_env is False, "trust_env must be False to ignore proxy env vars"
