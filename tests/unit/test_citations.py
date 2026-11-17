"""Unit tests for the citation tracker.

The headline test is :func:`test_reference_numbers_are_stable`: the original
implementation derived a citation's reference number from its position in an
ordered dict, so adding a source could renumber references already written into
a saved report.
"""

from __future__ import annotations

from coraxis.agents.citations import CitationTracker


def test_add_source_returns_stable_id() -> None:
    tracker = CitationTracker()
    first = tracker.add_source("https://example.com/a", title="A", relevance=0.5)
    second = tracker.add_source("https://example.com/a", title="A again", relevance=0.9)

    assert first == second, "the same URL must not create a second citation"
    assert len(tracker) == 1
    # Re-registering raises relevance to the best value seen.
    assert tracker.citations[0].relevance == 0.9


def test_blank_urls_are_ignored() -> None:
    tracker = CitationTracker()
    assert tracker.add_source("") == ""
    assert tracker.add_source("   ") == ""
    assert len(tracker) == 0


def test_reference_numbers_are_stable_across_later_additions() -> None:
    """The regression this module exists to prevent."""
    tracker = CitationTracker()
    tracker.add_source("https://first.example", relevance=0.5)
    tracker.add_claim("First claim", ["https://first.example"])

    marker_before = tracker.inline_markers("claim_0001")
    assert marker_before == "[^1]"

    # Adding more sources must not renumber what was already written.
    tracker.add_source("https://second.example", relevance=0.5)
    tracker.add_source("https://third.example", relevance=0.5)

    assert tracker.inline_markers("claim_0001") == marker_before
    assert tracker.citation_for_url("https://first.example").number == 1  # type: ignore[union-attr]


def test_numbers_are_never_reused() -> None:
    tracker = CitationTracker()
    for index in range(5):
        tracker.add_source(f"https://example.com/{index}")

    numbers = [citation.number for citation in tracker.citations]
    assert numbers == [1, 2, 3, 4, 5]
    assert len(set(numbers)) == len(numbers)


def test_claim_links_to_its_sources() -> None:
    tracker = CitationTracker()
    claim_id = tracker.add_claim(
        "The sky is blue.",
        ["https://a.example", "https://b.example"],
        confidence=0.8,
        agent="analyst",
        relevance_scores=[0.9, 0.4],
    )

    assert claim_id == "claim_0001"
    assert tracker.inline_markers(claim_id) == "[^1][^2]"

    citations = {citation.url: citation for citation in tracker.citations}
    assert citations["https://a.example"].relevance == 0.9
    assert citations["https://b.example"].relevance == 0.4
    assert claim_id in citations["https://a.example"].claim_refs


def test_empty_claim_text_is_rejected() -> None:
    tracker = CitationTracker()
    assert tracker.add_claim("", ["https://a.example"]) == ""
    assert tracker.claims == []


def test_confidence_is_clamped() -> None:
    tracker = CitationTracker()
    tracker.add_claim("Overconfident", ["https://a.example"], confidence=5.0)
    tracker.add_claim("Underconfident", ["https://b.example"], confidence=-3.0)

    assert tracker.claims[0].confidence == 1.0
    assert tracker.claims[1].confidence == 0.0


def test_markdown_includes_every_source_with_a_relevance_bar() -> None:
    tracker = CitationTracker()
    tracker.add_source("https://example.com/report", title="A Report", relevance=0.75)
    tracker.add_source("https://example.com/other", title="Another", relevance=0.2)

    markdown = tracker.format_markdown()

    assert "[^1]: **A Report**" in markdown
    assert "[^2]: **Another**" in markdown
    assert "Relevance: 75%" in markdown
    assert "Relevance: 20%" in markdown


def test_markdown_is_empty_without_sources() -> None:
    assert CitationTracker().format_markdown() == ""


def test_stats_are_computed_from_content() -> None:
    tracker = CitationTracker()
    tracker.add_source("https://a.example", relevance=1.0, fetch_success=True)
    tracker.add_source("https://b.example", relevance=0.0)
    tracker.add_claim("Claim", ["https://a.example"], confidence=0.6)
    tracker.add_claim("Claim two", ["https://b.example"], confidence=0.4)

    stats = tracker.stats()

    assert stats["total_sources"] == 2
    assert stats["total_claims"] == 2
    assert stats["avg_relevance"] == 0.5
    assert stats["avg_confidence"] == 0.5
    assert stats["fetched_sources"] == 1


def test_payloads_match_the_repository_contract() -> None:
    """These dicts are fed straight into the database layer."""
    tracker = CitationTracker()
    tracker.add_source("https://a.example", title="A", relevance=0.8, word_count=900)
    tracker.add_claim("A claim", ["https://a.example"], confidence=0.7, agent="analyst")

    source = tracker.source_payload()[0]
    assert set(source) == {
        "url",
        "title",
        "relevance",
        "snippet",
        "word_count",
        "fetch_success",
        "source_category",
        "publication_date",
        "retrieval_date",
        "discovery_query",
        "duplicate_of",
    }

    claim = tracker.claim_payload()[0]
    assert claim["claim_ref"] == "claim_0001"
    assert claim["source_urls"] == ["https://a.example"]
    assert claim["agent"] == "analyst"


def test_reset_clears_everything() -> None:
    tracker = CitationTracker()
    tracker.add_source("https://a.example")
    tracker.add_claim("Claim", ["https://a.example"])

    tracker.reset()

    assert len(tracker) == 0
    assert tracker.claims == []
    # Numbering restarts, which is correct: the report is gone too.
    assert tracker.add_source("https://b.example") == "cite_1"


# ─── Citation integrity (validation) ───────────────────────────────────────


def test_claim_payload_excludes_fabricated_citation_ids() -> None:
    """claim_payload must not return citation IDs that were never registered.

    Even if a claim object carries a fabricated citation_id (e.g. cite_999),
    claim_payload must only include URLs for citations that actually exist in
    the tracker.
    """
    tracker = CitationTracker()
    tracker.add_source("https://a.example", title="A")
    tracker.add_claim(
        "A claim with fabricated citation.",
        ["https://a.example"],
        evidence_strength="high",
        contradicts=["claim_9999"],
    )

    payload = tracker.claim_payload()[0]
    assert payload["claim_ref"] == "claim_0001"
    assert payload["source_urls"] == ["https://a.example"]


def test_claim_with_only_fabricated_citations_has_empty_source_urls() -> None:
    """A claim whose only supporting citation IDs are fabricated must report
    no source URLs, because validate_citation_ids filters out unknown IDs."""
    tracker = CitationTracker()
    tracker.add_source("https://a.example", title="A")

    # Manually add a claim with a fabricated citation_id to simulate an LLM
    # hallucinating a source it never retrieved.
    claim_id = tracker.add_claim(
        "A claim with fabricated citation.",
        ["https://a.example"],
        evidence_strength="high",
    )
    tracker._claims[0].citation_ids.append("cite_999")

    payload = tracker.claim_payload()[0]
    assert payload["claim_ref"] == claim_id
    assert payload["source_urls"] == ["https://a.example"]
    assert "https://fabricated.example" not in payload["source_urls"]


def test_validate_citation_ids_filters_unknown() -> None:
    tracker = CitationTracker()
    tracker.add_source("https://a.example", title="A")
    tracker.add_source("https://b.example", title="B")

    valid = tracker.validate_citation_ids(["cite_1", "cite_999", "cite_2"])
    assert valid == ["cite_1", "cite_2"]


def test_claim_with_no_supporting_sources_is_insufficient() -> None:
    tracker = CitationTracker()
    tracker.add_source("https://a.example", title="A")

    claim_id = tracker.add_claim("Unsupported claim.", [], evidence_strength="high")

    claim = tracker.claims[0]
    assert claim.evidence_strength == "insufficient"
    assert claim.id == claim_id
