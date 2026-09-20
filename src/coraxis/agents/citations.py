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
from typing import Any
from urllib.parse import urlparse


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
        }


@dataclass
class Claim:
    """A synthesised statement and the sources backing it."""

    id: str
    text: str
    citation_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    agent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_ref": self.id,
            "text": self.text,
            "confidence": self.confidence,
            "agent": self.agent,
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
        self._by_url: dict[str, str] = {}
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
    ) -> str:
        """Register a source and return its citation id.

        Re-registering the same URL keeps the original reference number and
        raises relevance to the highest value seen, so a later, better-scored
        fetch of the same page improves the report without disturbing
        references already written.
        """
        url = (url or "").strip()
        if not url:
            return ""

        with self._lock:
            existing_id = self._by_url.get(url)
            if existing_id is not None:
                citation = self._citations[existing_id]
                citation.relevance = max(citation.relevance, relevance)
                if title and not citation.title:
                    citation.title = title
                if snippet and snippet not in citation.snippet:
                    citation.snippet = snippet[:600]
                if word_count:
                    citation.word_count = max(citation.word_count, word_count)
                citation.fetch_success = citation.fetch_success or fetch_success
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
            )
            self._by_url[url] = citation_id
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

            self._claims.append(
                Claim(
                    id=claim_id,
                    text=text,
                    citation_ids=citation_ids,
                    confidence=max(0.0, min(1.0, confidence)),
                    agent=agent,
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
                urls = [
                    self._citations[cid].url for cid in claim.citation_ids if cid in self._citations
                ]
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
            }

    def reset(self) -> None:
        with self._lock:
            self._citations.clear()
            self._claims.clear()
            self._by_url.clear()
            self._next_number = 1

    def __len__(self) -> int:
        with self._lock:
            return len(self._citations)
