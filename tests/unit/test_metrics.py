"""Tests for automatic research-quality metrics.

Metrics are deterministic functions of captured pipeline output, so these
tests verify exact values on synthetic inputs rather than approximating them.
"""

from __future__ import annotations

from coraxis.evaluation.metrics import (
    compute_metrics,
    metric_summary,
)


def test_compute_metrics_empty_output() -> None:
    metrics = compute_metrics(
        sources=[],
        claims=[],
        report_markdown="",
        search_queries=[],
        extraction_failures=[],
    )
    assert metrics.total_sources == 0
    assert metrics.fetch_success_rate == 0.0
    assert metrics.unique_domains == 0
    assert metrics.citation_resolution_rate == 1.0  # no markers -> vacuously resolved
    assert metrics.claim_source_coverage == 1.0  # no claims -> vacuously covered
    assert metrics.extraction_failure_count == 0
    assert metrics.search_query_count == 0


def test_compute_metrics_fetch_success_rate() -> None:
    sources = [
        {"url": "https://a.example", "fetch_success": True},
        {"url": "https://b.example", "fetch_success": False},
        {"url": "https://c.example", "fetch_success": True},
    ]
    metrics = compute_metrics(
        sources=sources,
        claims=[],
        report_markdown="",
        search_queries=[],
        extraction_failures=[],
    )
    assert metrics.total_sources == 3
    assert metrics.fetched_sources == 2
    assert metrics.fetch_success_rate == round(2 / 3, 4)


def test_compute_metrics_domain_concentration() -> None:
    sources = [
        {"url": "https://a.example/page1", "fetch_success": True},
        {"url": "https://a.example/page2", "fetch_success": True},
        {"url": "https://b.example/page1", "fetch_success": True},
    ]
    metrics = compute_metrics(
        sources=sources,
        claims=[],
        report_markdown="",
        search_queries=[],
        extraction_failures=[],
    )
    assert metrics.unique_domains == 2
    assert metrics.domain_concentration == round(2 / 3, 4)  # a.example is 2 of 3


def test_compute_metrics_duplicate_url_rate() -> None:
    sources = [
        {"url": "https://a.example", "fetch_success": True},
        {"url": "https://a.example", "fetch_success": True},
        {"url": "https://b.example", "fetch_success": True},
    ]
    metrics = compute_metrics(
        sources=sources,
        claims=[],
        report_markdown="",
        search_queries=[],
        extraction_failures=[],
    )
    assert metrics.duplicate_url_rate == round(1 / 3, 4)


def test_compute_metrics_citation_resolution() -> None:
    sources = [
        {"url": "https://a.example", "fetch_success": True},
        {"url": "https://b.example", "fetch_success": True},
    ]
    # Report cites [^1] and [^3]; [^3] does not resolve (only 2 sources).
    metrics = compute_metrics(
        sources=sources,
        claims=[],
        report_markdown="See [^1] and also [^3].",
        search_queries=[],
        extraction_failures=[],
    )
    assert metrics.citation_marker_count == 2
    assert metrics.resolved_citations == 1
    assert metrics.citation_resolution_rate == 0.5


def test_compute_metrics_claim_source_coverage() -> None:
    claims = [
        {"source_urls": ["https://a.example"]},
        {"source_urls": []},
        {"source_urls": ["https://b.example", "https://c.example"]},
    ]
    metrics = compute_metrics(
        sources=[],
        claims=claims,
        report_markdown="",
        search_queries=[],
        extraction_failures=[],
    )
    assert metrics.total_claims == 3
    assert metrics.claims_with_sources == 2
    assert metrics.claim_source_coverage == round(2 / 3, 4)


def test_compute_metrics_sources_with_metadata() -> None:
    sources = [
        {"url": "https://a.example", "title": "A", "snippet": "snip"},
        {"url": "https://b.example", "title": "", "snippet": "snip"},
        {"url": "https://c.example", "title": "C", "snippet": ""},
    ]
    metrics = compute_metrics(
        sources=sources,
        claims=[],
        report_markdown="",
        search_queries=[],
        extraction_failures=[],
    )
    assert metrics.sources_with_metadata == round(1 / 3, 4)


def test_compute_metrics_extraction_failures_and_queries() -> None:
    metrics = compute_metrics(
        sources=[],
        claims=[],
        report_markdown="",
        search_queries=["q1", "q2", "q3"],
        extraction_failures=["failed url", "another failure"],
    )
    assert metrics.search_query_count == 3
    assert metrics.extraction_failure_count == 2


def test_metric_to_dict_is_json_serializable() -> None:
    import json

    metrics = compute_metrics(
        sources=[{"url": "https://a.example", "fetch_success": True}],
        claims=[{"source_urls": ["https://a.example"]}],
        report_markdown="See [^1].",
        search_queries=["q1"],
        extraction_failures=[],
    )
    json.dumps(metrics.to_dict())  # must not raise


def test_metric_summary_is_readable() -> None:
    metrics = compute_metrics(
        sources=[{"url": "https://a.example", "fetch_success": True}],
        claims=[{"source_urls": ["https://a.example"]}],
        report_markdown="See [^1].",
        search_queries=["q1"],
        extraction_failures=[],
    )
    summary = metric_summary(metrics)
    assert "1 sources" in summary
    assert "100%" in summary or "1 domains" in summary


def test_invalid_urls_are_ignored() -> None:
    sources = [
        {"url": "not-a-url", "fetch_success": True},
        {"url": "https://a.example", "fetch_success": True},
        {"url": "", "fetch_success": True},
    ]
    metrics = compute_metrics(
        sources=sources,
        claims=[],
        report_markdown="",
        search_queries=[],
        extraction_failures=[],
    )
    assert metrics.total_sources == 3
    assert metrics.unique_domains == 1  # only https://a.example parses
