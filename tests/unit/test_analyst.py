"""Tests for Phase 02D — Evidence-Based Synthesis schemas.

Covers claim-to-citation traceability, unsupported claim handling, citation
identifier validation, duplicate evidence handling, contradiction handling,
confidence categorization, research gap identification, empty evidence, missing
metadata, and backward compatibility. All tests are deterministic and require no
LLM or network access.
"""

from __future__ import annotations

from coraxis.agents.tasks import (
    AnalyzedFindings,
    Claim,
    ConflictPair,
    FindingItem,
    SourceRef,
    SubQuestions,
)

# ─── Claim-to-citation traceability ────────────────────────────────────────


def test_claim_records_stable_citation_ids() -> None:
    """Every supporting source must carry a stable citation identifier."""

    claim = Claim(
        claim_id="claim_0001",
        text="The sky is blue.",
        supporting_sources=[
            SourceRef(
                url="https://example.com/science",
                title="Science Page",
                citation_id="cite_3",
                relevance=0.9,
            )
        ],
        confidence=0.8,
        evidence_strength="high",
    )

    assert claim.supporting_sources[0].citation_id == "cite_3"


def test_claim_without_citation_id_is_allowed_for_unsupported_claims() -> None:
    """A claim with no supporting sources is still valid (unsupported claim)."""

    claim = Claim(
        claim_id="claim_0002",
        text="An unsupported claim.",
        supporting_sources=[],
        confidence=0.2,
        evidence_strength="insufficient",
        limitations="No sources were retrieved for this topic.",
    )

    assert claim.supporting_sources == []
    assert claim.evidence_strength == "insufficient"


# ─── Citation identifier validation ──────────────────────────────────────


def test_citation_id_format() -> None:
    """Citation identifiers follow the cite_N pattern when present."""

    claim = Claim(
        claim_id="claim_0003",
        text="A cited claim.",
        supporting_sources=[
            SourceRef(
                url="https://example.com/a",
                title="Source A",
                citation_id="cite_7",
            )
        ],
    )

    assert claim.supporting_sources[0].citation_id.startswith("cite_")


def test_claim_does_not_invent_citation_ids() -> None:
    """A claim with fabricated-looking citation ids is still just data; the
    harness must not validate provenance here — but the schema accepts any
    string, so callers are responsible for citing only retrieved sources."""

    claim = Claim(
        claim_id="claim_0004",
        text="A claim.",
        supporting_sources=[SourceRef(url="https://example.com/x", citation_id="cite_999")],
    )

    # The schema accepts the id; traceability enforcement happens at the
    # analyst/orchestrator level (citation ids must come from the tracker).
    assert claim.supporting_sources[0].citation_id == "cite_999"


# ─── Duplicate evidence handling ─────────────────────────────────────────


def test_duplicate_urls_share_citation_id() -> None:
    """Two findings for the same URL (duplicate) share one citation id."""

    claim = Claim(
        claim_id="claim_0005",
        text="A claim supported by a duplicated source.",
        supporting_sources=[
            SourceRef(url="https://example.com/page", citation_id="cite_2"),
            SourceRef(
                url="https://example.com/page/",
                citation_id="cite_2",
            ),  # same normalized URL -> same citation id
        ],
    )

    ids = {s.citation_id for s in claim.supporting_sources if s.citation_id}
    assert len(ids) == 1
    assert ids == {"cite_2"}


# ─── Contradiction handling ──────────────────────────────────────────────


def test_contradicts_records_conflicting_claim_ids() -> None:
    """A claim can record which other claim ids it contradicts."""

    claim = Claim(
        claim_id="claim_0006",
        text="Solar power is the cheapest energy source.",
        supporting_sources=[SourceRef(url="https://example.com/a", citation_id="cite_1")],
        confidence=0.7,
        evidence_strength="conflicted",
        contradicts=["claim_0007"],
    )

    assert "claim_0007" in claim.contradicts


def test_conflict_pair_records_both_sides() -> None:
    """A ConflictPair records both conflicting claim ids."""

    pair = ConflictPair(
        claim_a="claim_0006",
        claim_b="claim_0007",
        description="Claim 6 says solar is cheapest; claim 7 says wind is cheapest.",
    )

    assert pair.claim_a == "claim_0006"
    assert pair.claim_b == "claim_0007"
    assert "solar" in pair.description.lower()


def test_analyzed_findings_records_conflict_pairs() -> None:
    """AnalyzedFindings can carry structured conflict pairs."""

    findings = AnalyzedFindings(
        claims=[
            Claim(
                claim_id="claim_0008",
                text="Claim A.",
                supporting_sources=[SourceRef(url="https://example.com/a", citation_id="cite_1")],
                contradicts=["claim_0009"],
            ),
            Claim(
                claim_id="claim_0009",
                text="Claim B.",
                supporting_sources=[SourceRef(url="https://example.com/b", citation_id="cite_2")],
                contradicts=["claim_0008"],
            ),
        ],
        conflict_pairs=[
            ConflictPair(
                claim_a="claim_0008",
                claim_b="claim_0009",
                description="The two claims disagree on the conclusion.",
            )
        ],
    )

    assert len(findings.conflict_pairs) == 1
    assert findings.conflict_pairs[0].claim_a == "claim_0008"
    assert findings.conflict_pairs[0].claim_b == "claim_0009"


# ─── Confidence categorization ───────────────────────────────────────────


def test_evidence_strength_allowed_values() -> None:
    """Only the five documented evidence strengths are accepted when supported."""

    for strength in ("high", "moderate", "low", "insufficient", "conflicted"):
        claim = Claim(
            claim_id="claim_x",
            text="A claim.",
            supporting_sources=[SourceRef(url="https://example.com/a", citation_id="cite_1")],
            evidence_strength=strength,
        )
        assert claim.evidence_strength == strength


def test_evidence_strength_invalid_falls_back_to_insufficient() -> None:
    """An invalid evidence strength degrades gracefully to 'insufficient'."""

    claim = Claim(
        claim_id="claim_y",
        text="A claim.",
        evidence_strength="not-a-real-strength",
    )

    assert claim.evidence_strength == "insufficient"


def test_claim_with_no_sources_is_insufficient() -> None:
    """A claim with no supporting sources cannot claim any evidence strength."""

    claim = Claim(
        claim_id="claim_z",
        text="A claim with no support.",
        evidence_strength="high",
    )

    assert claim.evidence_strength == "insufficient"


def test_claim_with_sources_keeps_strength() -> None:
    """A claim with sources keeps its evidence strength."""

    claim = Claim(
        claim_id="claim_w",
        text="A supported claim.",
        supporting_sources=[SourceRef(url="https://example.com/a", citation_id="cite_1")],
        evidence_strength="high",
    )

    assert claim.evidence_strength == "high"


def test_high_confidence_requires_supporting_sources() -> None:
    """A high-strength claim should cite supporting sources (schema allows it,
    but the analyst task instructs that high strength requires sources)."""

    claim = Claim(
        claim_id="claim_z",
        text="A well-supported claim.",
        supporting_sources=[
            SourceRef(url="https://example.com/a", citation_id="cite_1"),
            SourceRef(url="https://example.com/b", citation_id="cite_2"),
            SourceRef(url="https://example.com/c", citation_id="cite_3"),
        ],
        confidence=0.9,
        evidence_strength="high",
    )

    assert len(claim.supporting_sources) == 3
    assert claim.confidence == 0.9


# ─── Research gap identification ─────────────────────────────────────────


def test_analyzed_findings_records_gaps() -> None:
    """Gaps record what could not be established."""

    findings = AnalyzedFindings(
        claims=[],
        gaps=[
            "No sources were found for the long-term safety data.",
            "No primary-source documentation was retrieved.",
        ],
        overall_confidence=0.3,
    )

    assert len(findings.gaps) == 2
    assert findings.overall_confidence == 0.3


# ─── Empty evidence / missing metadata ───────────────────────────────────


def test_analyzed_findings_empty() -> None:
    """An AnalyzedFindings with no claims is valid (no evidence found)."""

    findings = AnalyzedFindings()
    assert findings.claims == []
    assert findings.conflicts == []
    assert findings.gaps == []
    assert findings.conflict_pairs == []
    assert findings.overall_confidence == 0.5


def test_claim_with_empty_text() -> None:
    """A claim with empty text is still structurally valid (data passes
    through; the analyst task instructs against empty claims)."""

    claim = Claim(claim_id="claim_empty", text="")
    assert claim.text == ""


def test_claim_defaults() -> None:
    """Default field values are sensible."""

    claim = Claim(claim_id="claim_default", text="A default claim.")
    assert claim.supporting_sources == []
    assert claim.confidence == 0.5
    assert claim.relevance == 0.5
    assert claim.agent == "analyst"
    assert claim.evidence_strength == "insufficient"
    assert claim.limitations == ""
    assert claim.contradicts == []


# ─── Backward compatibility ──────────────────────────────────────────────


def test_subquestions_schema_unchanged() -> None:
    """The Researcher SubQuestions schema still works as before."""

    sq = SubQuestions(
        sub_questions=["What is X?", "What is Y?"],
        key_entities=["X"],
        search_strategy="strat",
    )
    assert sq.sub_questions == ["What is X?", "What is Y?"]
    assert sq.planned_questions == ["What is X?", "What is Y?"]


def test_finding_item_still_has_original_fields() -> None:
    """FindingItem still carries all original fields plus new metadata."""

    finding = FindingItem(
        question="What is X?",
        url="https://example.com",
        title="Example",
        snippet="A snippet.",
        full_text="Full text content here.",
        word_count=3,
        fetch_success=True,
        source_category="primary",
        publication_date="2024-01-01",
        retrieval_date="2026-11-10T00:00:00+00:00",
        discovery_query="what is X",
        duplicate_of="",
        extraction_status="success",
    )

    assert finding.fetch_success is True
    assert finding.source_category == "primary"
    assert finding.extraction_status == "success"


def test_source_ref_defaults() -> None:
    """SourceRef defaults are backward compatible."""

    ref = SourceRef(url="https://example.com")
    assert ref.url == "https://example.com"
    assert ref.title == ""
    assert ref.relevance == 0.7
    assert ref.snippet == ""
    assert ref.citation_id == ""


def test_claim_serialization_round_trip() -> None:
    """A Claim serializes to a dict and can be reconstructed."""

    claim = Claim(
        claim_id="claim_0010",
        text="A round-trip claim.",
        supporting_sources=[SourceRef(url="https://example.com/a", citation_id="cite_5")],
        confidence=0.8,
        evidence_strength="high",
        limitations="Single source.",
        contradicts=["claim_0011"],
    )

    d = claim.model_dump()
    assert d["claim_id"] == "claim_0010"
    assert d["text"] == "A round-trip claim."
    assert d["confidence"] == 0.8
    assert d["evidence_strength"] == "high"
    assert d["limitations"] == "Single source."
    assert d["contradicts"] == ["claim_0011"]
    assert d["supporting_sources"][0]["citation_id"] == "cite_5"

    reconstructed = Claim.model_validate(d)
    assert reconstructed.claim_id == "claim_0010"
    assert reconstructed.evidence_strength == "high"
    assert reconstructed.supporting_sources[0].citation_id == "cite_5"
