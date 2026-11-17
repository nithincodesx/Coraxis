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
import ipaddress
import re
import socket
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlparse

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

#: Schemes the fetcher is allowed to request. Everything else is rejected
#: before any network access.
_ALLOWED_SCHEMES = ("http", "https")

#: TCP ports the fetcher is allowed to connect to. Common web ports only;
#: this prevents SSRF-based port scanning of internal services on ports such
#: as SSH (22), SMTP (25), DNS (53), MySQL (3306), Redis (6379), etc.
_ALLOWED_PORTS = {80, 443, 8080, 8443}

#: Maximum number of redirect hops to follow manually. Prevents redirect
#: loops and limits exposure time to DNS changes between validation and
#: connection.
_MAX_REDIRECTS = 10

#: Hosts that always resolve to the local machine and must never be fetched.
_LOCALHOST_HOSTS = {"localhost", "localhost.localdomain", "ip6-loopback"}


def _resolve_host_ips(host: str) -> set[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """Resolve ``host`` to the set of IP addresses it currently points at.

    Returns an empty set when the host cannot be resolved (the caller decides
    whether to fail open or closed). DNS resolution is best-effort: the actual
    connection is still attempted by the HTTP client, so an unresolved host
    simply fails at connect time.

    WARNING: Because the HTTP client performs its own DNS resolution at
    connection time, there is a time-of-check-to-time-of-use (TOCTOU) window
    between this validation and the actual connection. A DNS rebinding attack
    could change the resolved address in that window. This validator reduces
    risk but cannot eliminate it when using a high-level HTTP client that
    performs its own resolution.
    """
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, socket.gaierror):
        return set()
    ips: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            ips.add(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    return ips


def _ipv4_mapped(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> ipaddress.IPv4Address | None:
    """Return the IPv4 address mapped by an IPv4-mapped IPv6 address, or None.

    IPv4-mapped IPv6 addresses (``::ffff:a.b.c.d``) are not caught by
    ``is_loopback`` (which only matches ``::1``) or ``is_private`` on the IPv6
    type, so they must be unwrapped to check the embedded IPv4 address.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        return ip.ipv4_mapped
    return None


def _ip_is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """True when ``ip`` is a private, loopback, link-local, multicast, or
    otherwise non-routable address that must never be fetched.

    Also unwraps IPv4-mapped IPv6 addresses (``::ffff:a.b.c.d``) so that an
    IPv4 loopback address embedded in IPv6 is not missed.
    """
    mapped = _ipv4_mapped(ip)
    if mapped is not None:
        ip = mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _host_is_allowed(host: str | None, port: int | None = None) -> bool:
    """True when fetching ``host``:``port`` is permitted by SSRF controls.

    Blocks IP literals that resolve to private/loopback/link-local addresses
    and the literal localhost name. For hostnames, resolves via DNS and blocks
    if any resolved address is blocked, which mitigates simple DNS rebinding.

    Also rejects non-standard ports (anything outside :data:`_ALLOWED_PORTS`).
    """
    host = (host or "").strip().lower()
    if not host:
        return False

    # Reject non-standard ports.
    if port is not None and port not in _ALLOWED_PORTS:
        return False

    if host in _LOCALHOST_HOSTS:
        return False

    # IP literal: check directly, no DNS needed.
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None:
        return not _ip_is_blocked(ip)

    # Hostname: resolve and check every returned address.
    return all(not _ip_is_blocked(ip) for ip in _resolve_host_ips(host))


def _url_has_credentials(parsed) -> bool:
    """True when the URL embeds username/password credentials.

    Embedded credentials leak authentication material to the fetched host and
    are a strong signal of a malicious URL. They are rejected outright.
    """
    return bool(parsed.username or parsed.password)


def _url_is_fetchable(url: str) -> str | None:
    """Return an error message when ``url`` must not be fetched, else ``None``.

    Checks scheme, host, port, and credentials. Redirect destinations are
    checked separately after the response arrives (see
    :meth:`PageFetcher.fetch`).
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return "Unparseable URL"
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return f"Unsupported scheme: {parsed.scheme or '(none)'}"
    if not parsed.hostname:
        return "URL has no host"
    if _url_has_credentials(parsed):
        return "URL contains embedded credentials"
    if not _host_is_allowed(parsed.hostname, parsed.port):
        return f"Blocked host: {parsed.hostname}"
    return None


class _UrlRejected(Exception):
    """Raised internally when a URL or redirect destination is blocked."""


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


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
    #: ISO-8601 timestamp of when the fetch was attempted.
    retrieved_at: str = ""

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
        """The shared client, created on first use.

        ``trust_env=False`` prevents proxy environment variables
        (``HTTP_PROXY``, ``HTTPS_PROXY``, ``ALL_PROXY``) from being honored,
        which stops a proxy-based bypass of the SSRF host allowlist.
        ``follow_redirects=False`` keeps redirect handling under our control so
        every hop can be validated before connecting.
        """
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=False,
                trust_env=False,
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

        Redirects are followed manually (``follow_redirects=False``) so that
        every hop is validated against the SSRF allowlist before connecting.
        This prevents httpx from automatically connecting to a blocked redirect
        target before we can inspect it.
        """
        started = time.perf_counter()
        url = (url or "").strip()
        if not url:
            return FetchedPage(url=url, error="Empty URL")

        last_error = ""
        current_url = url
        redirect_count = 0

        for attempt in range(self.max_retries + 1):
            try:
                # Follow redirects within this attempt. Each hop is validated
                # against the SSRF allowlist before connecting.
                while True:
                    blocked = _url_is_fetchable(current_url)
                    if blocked is not None:
                        return FetchedPage(
                            url=current_url,
                            fetch_time=time.perf_counter() - started,
                            error=blocked,
                            retrieved_at=_now_iso(),
                        )

                    response = await self.client.get(current_url)
                    response.raise_for_status()

                    if response.is_redirect:
                        redirect_count += 1
                        if redirect_count > _MAX_REDIRECTS:
                            return FetchedPage(
                                url=str(response.url),
                                fetch_time=time.perf_counter() - started,
                                error="Too many redirects",
                                retrieved_at=_now_iso(),
                            )
                        location = response.headers.get("location")
                        if not location:
                            return FetchedPage(
                                url=str(response.url),
                                fetch_time=time.perf_counter() - started,
                                error="Redirect with no Location header",
                                retrieved_at=_now_iso(),
                            )
                        # Resolve relative redirect targets against the response URL.
                        current_url = urljoin(str(response.url), location)
                        continue

                    break  # Not a redirect: exit the inner redirect loop

                content_type = response.headers.get("content-type", "").lower()
                if content_type and not any(kind in content_type for kind in _EXTRACTABLE):
                    return FetchedPage(
                        url=str(response.url),
                        fetch_time=time.perf_counter() - started,
                        error=f"Unsupported content type: {content_type.split(';')[0]}",
                        retrieved_at=_now_iso(),
                    )

                html = response.text
                title, text = await asyncio.to_thread(self._extract, html, str(response.url))

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
                        retrieved_at=_now_iso(),
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
