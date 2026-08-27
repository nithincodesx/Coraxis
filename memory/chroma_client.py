"""
ChromaDB Embedded Client — semantic memory for research topics.
Persists to ./chroma_db/ and uses sentence-transformers for embeddings.
"""

from __future__ import annotations

import os
import uuid
import time
from typing import Any, Optional
from pathlib import Path
from dataclasses import dataclass, asdict

try:
    import chromadb
    from chromadb.utils import embedding_functions
except ImportError:
    chromadb = None
    embedding_functions = None


CHROMA_DIR = Path(__file__).parent.parent / "chroma_db"
CHROMA_DIR.mkdir(exist_ok=True, parents=True)


@dataclass
class MemoryEntry:
    """A stored research finding."""
    id: str
    topic: str
    claim: str
    sources: list[str]
    confidence: float
    relevance: float
    agent: str
    timestamp: float
    metadata: dict[str, Any] = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

    def to_chroma_metadata(self) -> dict[str, Any]:
        """Convert to ChromaDB-compatible metadata (str/float/int/bool only)."""
        return {
            "topic": self.topic,
            "claim": self.claim,
            "sources": ", ".join(self.sources),
            "confidence": self.confidence,
            "relevance": self.relevance,
            "agent": self.agent,
            "timestamp": self.timestamp,
            **self.metadata,
        }

    @classmethod
    def from_chroma(cls, doc: str, metadata: dict[str, Any], id: str) -> "MemoryEntry":
        return cls(
            id=id,
            topic=metadata.get("topic", ""),
            claim=doc,
            sources=metadata.get("sources", "").split(", ") if metadata.get("sources") else [],
            confidence=metadata.get("confidence", 0.0),
            relevance=metadata.get("relevance", 0.0),
            agent=metadata.get("agent", ""),
            timestamp=metadata.get("timestamp", 0.0),
            metadata={k: v for k, v in metadata.items() if k not in (
                "topic", "sources", "confidence", "relevance", "agent", "timestamp"
            )},
        )


class ChromaMemory:
    """
    Embedded ChromaDB client for research memory.
    One collection per topic (slugified).
    """

    def __init__(self, persist_dir: str | Path = CHROMA_DIR):
        self.persist_dir = Path(persist_dir)
        self.persist_dir.mkdir(exist_ok=True, parents=True)

        # Use sentence-transformers for embeddings (local, no API key)
        self.embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="all-MiniLM-L6-v2"
        )

        self._client: Optional[chromadb.Client] = None
        self._collections: dict[str, chromadb.Collection] = {}

    @property
    def client(self) -> chromadb.Client:
        """Lazy-initialize ChromaDB client."""
        if self._client is None:
            self._client = chromadb.PersistentClient(
                path=str(self.persist_dir),
                settings=chromadb.Settings(
                    anonymized_telemetry=False,
                    allow_reset=True,
                ),
            )
        return self._client

    def _slugify(self, topic: str) -> str:
        """Create valid collection name from topic."""
        import re
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", topic.lower().strip())
        slug = re.sub(r"_+", "_", slug).strip("_")
        return slug[:50] or "research"

    def get_collection(self, topic: str) -> chromadb.Collection:
        """Get or create collection for a topic."""
        slug = self._slugify(topic)
        if slug not in self._collections:
            self._collections[slug] = self.client.get_or_create_collection(
                name=slug,
                embedding_function=self.embedding_fn,
                metadata={"topic": topic, "created": time.time()},
            )
        return self._collections[slug]

    def upsert_findings(self, topic: str, findings: list[MemoryEntry]) -> int:
        """
        Store research findings in the topic collection.
        Returns number of entries added.
        """
        if not findings:
            return 0

        collection = self.get_collection(topic)

        ids = [f.id for f in findings]
        documents = [f.claim for f in findings]
        metadatas = [f.to_chroma_metadata() for f in findings]

        collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        return len(findings)

    def query_similar(
        self,
        topic: str,
        query_text: str,
        n_results: int = 5,
        min_confidence: float = 0.0,
    ) -> list[MemoryEntry]:
        """
        Semantic search for similar prior findings.
        Returns MemoryEntry objects sorted by relevance score.
        """
        collection = self.get_collection(topic)

        # ChromaDB query
        results = collection.query(
            query_texts=[query_text],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )

        entries = []
        if results["ids"] and results["ids"][0]:
            for i, doc_id in enumerate(results["ids"][0]):
                metadata = results["metadatas"][0][i]
                doc = results["documents"][0][i]
                distance = results["distances"][0][i] if results["distances"] else 1.0

                # Convert distance to similarity (lower distance = higher similarity)
                similarity = 1.0 - min(distance, 1.0)

                # Filter by min_confidence
                if metadata.get("confidence", 0.0) >= min_confidence:
                    entry = MemoryEntry.from_chroma(doc, metadata, doc_id)
                    entry.metadata["similarity"] = similarity
                    entries.append(entry)

        # Sort by similarity (highest first)
        entries.sort(key=lambda e: e.metadata.get("similarity", 0), reverse=True)
        return entries

    def get_topic_stats(self, topic: str) -> dict[str, Any]:
        """Get statistics for a topic collection."""
        try:
            collection = self.get_collection(topic)
            count = collection.count()
            return {"topic": topic, "entry_count": count}
        except Exception:
            return {"topic": topic, "entry_count": 0, "error": "Collection not found"}

    def list_topics(self) -> list[str]:
        """List all topic collections."""
        try:
            cols = self.client.list_collections()
            return [c.name for c in cols]
        except Exception:
            return []

    def delete_topic(self, topic: str) -> bool:
        """Delete a topic collection."""
        slug = self._slugify(topic)
        try:
            self.client.delete_collection(name=slug)
            self._collections.pop(slug, None)
            return True
        except Exception:
            return False


# Singleton instance
_memory_instance: Optional[ChromaMemory] = None


def get_memory() -> ChromaMemory:
    """Get singleton ChromaMemory instance."""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = ChromaMemory()
    return _memory_instance


# Convenience functions
def remember_findings(topic: str, findings: list[MemoryEntry]) -> int:
    """Store findings for a topic."""
    return get_memory().upsert_findings(topic, findings)


def recall_similar(topic: str, query: str, n: int = 5) -> list[MemoryEntry]:
    """Recall similar prior findings."""
    return get_memory().query_similar(topic, query, n_results=n)


def make_memory_entry(
    topic: str,
    claim: str,
    sources: list[str],
    confidence: float,
    relevance: float,
    agent: str,
) -> MemoryEntry:
    """Factory for MemoryEntry."""
    return MemoryEntry(
        id=f"mem_{uuid.uuid4().hex[:12]}",
        topic=topic,
        claim=claim,
        sources=sources,
        confidence=confidence,
        relevance=relevance,
        agent=agent,
        timestamp=time.time(),
    )