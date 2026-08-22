"""
Citation Tracker — records source URL + relevance score per claim.
Produces formatted markdown with inline citations [^1] and reference list.
"""

import json
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Optional
from collections import OrderedDict


@dataclass
class CitationEntry:
    """A single citation entry."""
    id: str
    url: str
    title: str
    relevance: float  # 0.0 - 1.0
    snippet: str = ""
    claim_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @property
    def relevance_pct(self) -> int:
        return int(round(self.relevance * 100))

    @property
    def short_url(self) -> str:
        """Truncated URL for display."""
        from urllib.parse import urlparse
        parsed = urlparse(self.url)
        return f"{parsed.netloc}{parsed.path[:50]}"


@dataclass
class ClaimEntry:
    """A claim with its supporting citations."""
    id: str
    text: str
    citation_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0  # 0.0 - 1.0
    agent: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CitationTracker:
    """
    Tracks citations and claims during a research run.
    Provides markdown formatting with inline [^n] references.
    """

    def __init__(self):
        self.citations: OrderedDict[str, CitationEntry] = OrderedDict()
        self.claims: list[ClaimEntry] = []
        self._url_to_citation_id: dict[str, str] = {}
        self._next_citation_num = 1

    def add_source(
        self,
        url: str,
        title: str,
        relevance: float,
        snippet: str = "",
    ) -> str:
        """
        Add or update a source. Returns citation ID.
        If URL already exists, updates relevance to max of old/new.
        """
        if url in self._url_to_citation_id:
            cit_id = self._url_to_citation_id[url]
            entry = self.citations[cit_id]
            if relevance > entry.relevance:
                entry.relevance = relevance
            if snippet and snippet not in entry.snippet:
                entry.snippet = snippet[:500]
            return cit_id

        cit_id = f"cite_{self._next_citation_num}"
        self._next_citation_num += 1

        entry = CitationEntry(
            id=cit_id,
            url=url,
            title=title or url,
            relevance=max(0.0, min(1.0, relevance)),
            snippet=snippet[:500],
        )
        self.citations[cit_id] = entry
        self._url_to_citation_id[url] = cit_id
        return cit_id

    def add_claim(
        self,
        text: str,
        source_urls: list[str],
        confidence: float = 0.7,
        agent: str = "",
        relevance_scores: Optional[list[float]] = None,
    ) -> str:
        """
        Add a claim with supporting source URLs.
        Creates citations for new URLs.
        Returns claim ID.
        """
        claim_id = f"claim_{uuid.uuid4().hex[:8]}"
        citation_ids = []

        for i, url in enumerate(source_urls):
            rel = relevance_scores[i] if relevance_scores and i < len(relevance_scores) else 0.7
            title = ""  # Will be filled if we have the page title
            cit_id = self.add_source(url, title, rel)
            citation_ids.append(cit_id)
            self.citations[cit_id].claim_ids.append(claim_id)

        claim = ClaimEntry(
            id=claim_id,
            text=text.strip(),
            citation_ids=citation_ids,
            confidence=max(0.0, min(1.0, confidence)),
            agent=agent,
        )
        self.claims.append(claim)
        return claim_id

    def get_citation(self, cit_id: str) -> Optional[CitationEntry]:
        return self.citations.get(cit_id)

    def get_claim(self, claim_id: str) -> Optional[ClaimEntry]:
        for c in self.claims:
            if c.id == claim_id:
                return c
        return None

    def format_inline(self, claim_id: str) -> str:
        """Format inline citation markers for a claim: [^1][^2]"""
        claim = self.get_claim(claim_id)
        if not claim:
            return ""
        markers = []
        for cit_id in claim.citation_ids:
            entry = self.citations.get(cit_id)
            if entry:
                # Find the citation number (1-indexed position)
                cit_num = list(self.citations.keys()).index(cit_id) + 1
                markers.append(f"[^{cit_num}]")
        return "".join(markers)

    def format_markdown(self) -> str:
        """
        Generate full markdown with:
        1. Inline citations in claims (handled externally)
        2. Reference list at bottom
        """
        if not self.citations:
            return ""

        lines = ["\n---\n### Sources\n"]
        for i, (cit_id, entry) in enumerate(self.citations.items(), 1):
            relevance_bar = self._relevance_bar(entry.relevance)
            lines.append(
                f"[^{i}]: **{entry.title}** — {entry.url}  "
                f"{relevance_bar} Relevance: {entry.relevance_pct}%"
            )
            if entry.snippet:
                lines.append(f"    > {entry.snippet[:200]}...")
            lines.append("")

        return "\n".join(lines)

    def _relevance_bar(self, relevance: float, width: int = 10) -> str:
        """Generate a text-based relevance bar."""
        filled = int(round(relevance * width))
        empty = width - filled
        return f"`{'█' * filled}{'░' * empty}`"

    def to_json(self) -> str:
        """Serialize to JSON for storage/transfer."""
        return json.dumps({
            "citations": [c.to_dict() for c in self.citations.values()],
            "claims": [c.to_dict() for c in self.claims],
        }, ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, data: str) -> "CitationTracker":
        """Deserialize from JSON."""
        tracker = cls()
        obj = json.loads(data)
        for c in obj.get("citations", []):
            entry = CitationEntry(**c)
            tracker.citations[entry.id] = entry
            tracker._url_to_citation_id[entry.url] = entry.id
        for c in obj.get("claims", []):
            tracker.claims.append(ClaimEntry(**c))
        tracker._next_citation_num = len(tracker.citations) + 1
        return tracker

    def get_stats(self) -> dict[str, Any]:
        """Get summary statistics."""
        if not self.citations:
            return {"total_sources": 0, "total_claims": 0, "avg_relevance": 0, "avg_confidence": 0}

        avg_rel = sum(c.relevance for c in self.citations.values()) / len(self.citations)
        avg_conf = sum(c.confidence for c in self.claims) / len(self.claims) if self.claims else 0
        return {
            "total_sources": len(self.citations),
            "total_claims": len(self.claims),
            "avg_relevance": round(avg_rel, 3),
            "avg_confidence": round(avg_conf, 3),
        }

    def clear(self):
        """Reset for new run."""
        self.citations.clear()
        self.claims.clear()
        self._url_to_citation_id.clear()
        self._next_citation_num = 1