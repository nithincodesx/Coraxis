"""Citation tracking.

Records the sources a run consulted and the claims it synthesised from them,
then renders the ``[^n]`` markdown reference list.

The important design decision here is that a citation's reference *number* is
assigned once, when the source is first seen, and never recomputed. The earlier
implementation derived the number from the citation's position in an ordered
dict, which meant that adding a source could silently renumber references
already written into a saved report.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from coraxis.agents.tools.source_utils import normalize_url


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class Citation:
    """One source, with the reference number it will always carry."""

    id: str
    number: int
    url: str
    title: str
    relevance: float
    snippet: str = ""
    word_count: int = 0
    fetch_success: bool = False
    claim_refs: list[str] = field(default_factory=list)
    #: Heuristic source category (primary / academic / news / official_documentation / general).
    #: Labelled heuristic throughout — never presented as verified authority.
    source_category: str = "general"
    #: Publication date if discoverable, ISO-8601 where possible. Empty when unknown.
    publication_date: str = ""
    #: Retrieval timestamp, ISO-8601.
    retrieval_date: str = ""
    #: Search query that discovered this source.
    discovery_query: str = ""
    #: Citation id of the canonical source when this URL is a duplicate.
    duplicate_of: str = ""

    @property
    def relevance_pct(self) -> int:
        return round(max(0.0, min(1.0, self.relevance)) * 100)

    @property
    def display_domain(self) -> str:
        try:
            return urlparse(self.url).netloc or self.url
        except ValueError:
            return self.url

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.title,
            "relevance": self.relevance,
            "snippet": self.snippet,
            "word_count": self.word_count,
            "fetch_success": self.fetch_success,
            "source_category": self.source_category,
            "publication_date": self.publication_date,
            "retrieval_date": self.retrieval_date,
            "discovery_query": self.discovery_query,
            "duplicate_of": self.duplicate_of,
        }


@dataclass
class Claim:
    """A synthesised statement and the sources backing it."""

    id: str
    text: str
    citation_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    agent: str = ""
    #: Evidence strength category: high / moderate / low / insufficient / conflicted.
    evidence_strength: str = "insufficient"
    #: Limitations or caveats about the evidence supporting this claim.
    limitations: str = ""
    #: Claim identifiers this claim contradicts.
    contradicts: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_ref": self.id,
            "text": self.text,
            "confidence": self.confidence,
            "agent": self.agent,
            "evidence_strength": self.evidence_strength,
            "limitations": self.limitations,
            "contradicts": self.contradicts,
        }


class CitationTracker:
    """Thread-safe accumulator for a single run's evidence.

    Thread safety matters because CrewAI may invoke tools from a worker thread
    while the orchestrator reads progress from the event loop.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._citations: dict[str, Citation] = {}
        self._claims: list[Claim] = []
        self._by_url: dict[str, str] = {}  # raw url -> citation_id
        self._by_normalized: dict[str, str] = {}  # normalized url -> citation_id (dedup key)
        self._raw_to_canonical: dict[str, str] = {}  # raw duplicate url -> canonical citation_id
        self._discovered_count = 0
        self._duplicate_count = 0
        self._next_number = 1

    # ── Sources ──────────────────────────────────────────────────────

    def add_source(
        self,
        url: str,
        title: str = "",
        relevance: float = 0.0,
        snippet: str = "",
        *,
        word_count: int = 0,
        fetch_success: bool = False,
        source_category: str = "general",
        publication_date: str = "",
        retrieval_date: str = "",
        discovery_query: str = "",
    ) -> str:
        """Register a source and return its citation id.

        Sources are de-duplicated by normalized URL (see
        :func:`coraxis.agents.tools.source_utils.normalize_url`), so tracking
        parameters, trailing slashes, and scheme differences collapse onto one
        citation. Re-registering the same document keeps the original reference
        number and raises relevance to the highest value seen.
        """
        url = (url or "").strip()
        if not url:
            return ""

        normalized = normalize_url(url)
        retrieval_date = retrieval_date or _now_iso()

        with self._lock:
            self._discovered_count += 1

            existing_id = self._by_normalized.get(normalized)
            if existing_id is not None:
                self._duplicate_count += 1
                self._raw_to_canonical[url] = existing_id
                self._by_url[url] = existing_id
                citation = self._citations[existing_id]
                citation.relevance = max(citation.relevance, relevance)
                if title and not citation.title:
                    citation.title = title
                if snippet and snippet not in citation.snippet:
                    citation.snippet = snippet[:600]
                if word_count:
                    citation.word_count = max(citation.word_count, word_count)
                citation.fetch_success = citation.fetch_success or fetch_success
                if discovery_query and not citation.discovery_query:
                    citation.discovery_query = discovery_query
                if publication_date and not citation.publication_date:
                    citation.publication_date = publication_date
                return existing_id

            citation_id = f"cite_{self._next_number}"
            self._citations[citation_id] = Citation(
                id=citation_id,
                number=self._next_number,
                url=url,
                title=title.strip() or url,
                relevance=max(0.0, min(1.0, relevance)),
                snippet=snippet[:600],
                word_count=word_count,
                fetch_success=fetch_success,
                source_category=source_category,
                publication_date=publication_date,
                retrieval_date=retrieval_date,
                discovery_query=discovery_query,
            )
            self._by_url[url] = citation_id
            self._by_normalized[normalized] = citation_id
            self._raw_to_canonical[url] = citation_id
            self._next_number += 1
            return citation_id

    # ── Claims ───────────────────────────────────────────────────────

    def add_claim(
        self,
        text: str,
        source_urls: list[str],
        *,
        confidence: float = 0.7,
        agent: str = "",
        relevance_scores: list[float] | None = None,
        evidence_strength: str = "insufficient",
        limitations: str = "",
        contradicts: list[str] | None = None,
    ) -> str:
        """Register a claim against its supporting sources."""
        text = (text or "").strip()
        if not text:
            return ""

        with self._lock:
            claim_id = f"claim_{len(self._claims) + 1:04d}"
            citation_ids: list[str] = []

            for index, url in enumerate(source_urls or []):
                # Only an explicitly supplied score may move a source's
                # relevance. Falling back to a default here would let a claim
                # *raise* a measured value — a page scored 0.0 by the search
                # tool would jump to the default the moment a claim cited it,
                # inflating the relevance statistics the report is built on.
                if relevance_scores and index < len(relevance_scores):
                    citation_id = self.add_source(url, relevance=relevance_scores[index])
                else:
                    citation_id = self.add_source(url)
                if not citation_id:
                    continue
                citation_ids.append(citation_id)
                if claim_id not in self._citations[citation_id].claim_refs:
                    self._citations[citation_id].claim_refs.append(claim_id)

            # A claim with no supporting sources cannot claim any evidence
            # strength. Absence of evidence is not evidence of strength.
            if not citation_ids:
                evidence_strength = "insufficient"

            self._claims.append(
                Claim(
                    id=claim_id,
                    text=text,
                    citation_ids=citation_ids,
                    confidence=max(0.0, min(1.0, confidence)),
                    agent=agent,
                    evidence_strength=evidence_strength,
                    limitations=limitations,
                    contradicts=contradicts or [],
                )
            )
            return claim_id

    # ── Reading ──────────────────────────────────────────────────────

    @property
    def citations(self) -> list[Citation]:
        with self._lock:
            return sorted(self._citations.values(), key=lambda c: c.number)

    @property
    def claims(self) -> list[Claim]:
        with self._lock:
            return list(self._claims)

    def citation_for_url(self, url: str) -> Citation | None:
        with self._lock:
            citation_id = self._by_url.get(url)
            return self._citations.get(citation_id) if citation_id else None

    def validate_citation_ids(self, citation_ids: list[str]) -> list[str]:
        """Return the subset of citation_ids that exist in this tracker.

        Used to validate that a claim's supporting_sources only reference
        sources that were actually registered. Fabricated or unknown IDs are
        excluded rather than silently accepted.
        """
        with self._lock:
            return [cid for cid in citation_ids if cid in self._citations]

    def inline_markers(self, claim_id: str) -> str:
        """Render the ``[^n][^m]`` markers for one claim."""
        with self._lock:
            claim = next((c for c in self._claims if c.id == claim_id), None)
            if claim is None:
                return ""
            numbers = [
                self._citations[cid].number for cid in claim.citation_ids if cid in self._citations
            ]
        return "".join(f"[^{number}]" for number in sorted(numbers))

    def format_markdown(self) -> str:
        """Render the sources appendix."""
        with self._lock:
            citations = sorted(self._citations.values(), key=lambda c: c.number)
            if not citations:
                return ""

            lines = ["", "---", "", "### Sources", ""]
            for citation in citations:
                title = citation.title or citation.url
                lines.append(
                    f"[^{citation.number}]: **{title}** — <{citation.url}>  \n"
                    f"    `{self._relevance_bar(citation.relevance)}` "
                    f"Relevance: {citation.relevance_pct}%"
                )
                if citation.snippet:
                    lines.append(f"    > {citation.snippet[:200]}")
                lines.append("")
            return "\n".join(lines)

    @staticmethod
    def _relevance_bar(relevance: float, width: int = 10) -> str:
        filled = round(max(0.0, min(1.0, relevance)) * width)
        return "█" * filled + "░" * (width - filled)

    # ── Serialisation ────────────────────────────────────────────────

    def source_payload(self) -> list[dict[str, Any]]:
        """Sources shaped for ``repositories.runs.replace_sources``."""
        with self._lock:
            return [
                citation.to_dict()
                for citation in sorted(self._citations.values(), key=lambda c: c.number)
            ]

    def claim_payload(self) -> list[dict[str, Any]]:
        """Claims shaped for ``repositories.runs.replace_claims``."""
        with self._lock:
            payload = []
            for claim in self._claims:
                citation_ids = self.validate_citation_ids(claim.citation_ids)
                urls = [self._citations[cid].url for cid in citation_ids]
                relevance = (
                    sum(
                        self._citations[cid].relevance
                        for cid in claim.citation_ids
                        if cid in self._citations
                    )
                    / len(claim.citation_ids)
                    if claim.citation_ids
                    else 0.0
                )
                payload.append(
                    {
                        **claim.to_dict(),
                        "relevance": round(relevance, 4),
                        "source_urls": urls,
                    }
                )
            return payload
            return payload

    def stats(self) -> dict[str, Any]:
        with self._lock:
            citations = list(self._citations.values())
            claims = list(self._claims)

            avg_relevance = (
                sum(c.relevance for c in citations) / len(citations) if citations else 0.0
            )
            avg_confidence = sum(c.confidence for c in claims) / len(claims) if claims else 0.0

            return {
                "total_sources": len(citations),
                "total_claims": len(claims),
                "avg_relevance": round(avg_relevance, 4),
                "avg_confidence": round(avg_confidence, 4),
                "fetched_sources": sum(1 for c in citations if c.fetch_success),
                "discovered_sources": self._discovered_count,
                "duplicate_sources": self._duplicate_count,
            }

    def reset(self) -> None:
        with self._lock:
            self._citations.clear()
            self._claims.clear()
            self._by_url.clear()
            self._by_normalized.clear()
            self._raw_to_canonical.clear()
            self._discovered_count = 0
            self._duplicate_count = 0
            self._next_number = 1

    def __len__(self) -> int:
        with self._lock:
            return len(self._citations)
