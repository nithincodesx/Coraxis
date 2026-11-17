"""Automatic, reproducible research-quality metrics.

These metrics are computed from the captured pipeline output without any LLM
judgment. They complement the human rubric (see :mod:`coraxis.evaluation.scoring`)
and are reported alongside it — never substituted for it.

Every metric is deterministic given the same inputs, so baseline and
post-improvement results are directly comparable.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

_URL_SCHEME_RE = re.compile(r"^https?://", re.IGNORECASE)
_CITATION_RE = re.compile(r"\[\^(\d+)\]")


@dataclass
class AutomaticMetrics:
    """All automatically computed metrics for one benchmark case."""

    total_sources: int
    fetched_sources: int
    fetch_success_rate: float
    unique_domains: int
    domain_concentration: float
    duplicate_url_rate: float
    sources_with_metadata: float
    citation_marker_count: int
    resolved_citations: int
    citation_resolution_rate: float
    claims_with_sources: int
    total_claims: int
    claim_source_coverage: float
    extraction_failure_count: int
    search_query_count: int

    def to_dict(self) -> dict[str, float | int]:
        return {
            "total_sources": self.total_sources,
            "fetched_sources": self.fetched_sources,
            "fetch_success_rate": self.fetch_success_rate,
            "unique_domains": self.unique_domains,
            "domain_concentration": self.domain_concentration,
            "duplicate_url_rate": self.duplicate_url_rate,
            "sources_with_metadata": self.sources_with_metadata,
            "citation_marker_count": self.citation_marker_count,
            "resolved_citations": self.resolved_citations,
            "citation_resolution_rate": self.citation_resolution_rate,
            "claims_with_sources": self.claims_with_sources,
            "total_claims": self.total_claims,
            "claim_source_coverage": self.claim_source_coverage,
            "extraction_failure_count": self.extraction_failure_count,
            "search_query_count": self.search_query_count,
        }


def _domain(url: str) -> str:
    try:
        netloc = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return netloc


def _is_valid_url(url: str) -> bool:
    return bool(url) and bool(_URL_SCHEME_RE.match(url.strip()))


def compute_metrics(
    *,
    sources: list[dict[str, Any]],
    claims: list[dict[str, Any]],
    report_markdown: str,
    search_queries: list[str],
    extraction_failures: list[str],
) -> AutomaticMetrics:
    """Compute every automatic metric from captured pipeline output.

    Parameters
    ----------
    sources:
        Source dicts as emitted by :meth:`CitationTracker.source_payload`.
        Each dict carries ``url``, ``title``, ``relevance``, ``snippet``,
        ``word_count``, ``fetch_success``.
    claims:
        Claim dicts as emitted by :meth:`CitationTracker.claim_payload`.
        Each carries ``source_urls`` (list of resolved URLs).
    report_markdown:
        The final report text, used to count ``[^n]`` citation markers and
        check which ones resolve to registered sources.
    search_queries:
        The queries the pipeline actually sent to the search tool.
    extraction_failures:
        Queries or URLs that failed to fetch or extract.
    """
    total_sources = len(sources)
    fetched_sources = sum(1 for s in sources if s.get("fetch_success"))
    fetch_success_rate = fetched_sources / total_sources if total_sources else 0.0

    domains = [_domain(s.get("url", "")) for s in sources if _is_valid_url(s.get("url", ""))]
    unique_domains = len(set(domains))
    # Domain concentration: share of sources from the most common domain.
    domain_counts = Counter(domains)
    domain_concentration = (
        domain_counts.most_common(1)[0][1] / total_sources if total_sources else 0.0
    )

    # Duplicate URL rate: sources beyond the first occurrence of each URL.
    urls = [s.get("url", "") for s in sources]
    duplicate_url_rate = (total_sources - len(set(urls))) / total_sources if total_sources else 0.0

    sources_with_metadata = (
        sum(1 for s in sources if s.get("title") and s.get("snippet")) / total_sources
        if total_sources
        else 0.0
    )

    # Citation markers present in the report.
    markers = [int(m) for m in _CITATION_RE.findall(report_markdown)]
    citation_marker_count = len(markers)

    # Registered citation numbers (1-based, stable per URL).
    registered_numbers = {i + 1 for i in range(total_sources)}
    resolved_citations = sum(1 for n in markers if n in registered_numbers)
    citation_resolution_rate = (
        resolved_citations / citation_marker_count if citation_marker_count else 1.0
    )

    total_claims = len(claims)
    claims_with_sources = sum(1 for c in claims if c.get("source_urls"))
    claim_source_coverage = claims_with_sources / total_claims if total_claims else 1.0

    return AutomaticMetrics(
        total_sources=total_sources,
        fetched_sources=fetched_sources,
        fetch_success_rate=round(fetch_success_rate, 4),
        unique_domains=unique_domains,
        domain_concentration=round(domain_concentration, 4),
        duplicate_url_rate=round(duplicate_url_rate, 4),
        sources_with_metadata=round(sources_with_metadata, 4),
        citation_marker_count=citation_marker_count,
        resolved_citations=resolved_citations,
        citation_resolution_rate=round(citation_resolution_rate, 4),
        claims_with_sources=claims_with_sources,
        total_claims=total_claims,
        claim_source_coverage=round(claim_source_coverage, 4),
        extraction_failure_count=len(extraction_failures),
        search_query_count=len(search_queries),
    )


def metric_summary(metrics: AutomaticMetrics) -> str:
    """Human-readable one-line summary of the automatic metrics."""
    return (
        f"{metrics.total_sources} sources, "
        f"{metrics.fetch_success_rate:.0%} fetch success, "
        f"{metrics.unique_domains} domains, "
        f"{metrics.citation_resolution_rate:.0%} citations resolved, "
        f"{metrics.claim_source_coverage:.0%} claims sourced, "
        f"{metrics.extraction_failure_count} extraction failures"
    )
