"""Semantic memory over ChromaDB.

Two changes from the original implementation matter:

1. **Collections are namespaced per user.** The previous version derived the
   collection name from the topic alone, which meant one user's stored findings
   could surface in another user's research. Collections are now keyed by
   ``u<user>_<topic>``.
2. **Every call is offloaded to a thread.** Chroma and the sentence-transformers
   embedding function are synchronous and CPU-heavy; calling them directly from
   an async route would stall the event loop for hundreds of milliseconds.
"""

from __future__ import annotations

import asyncio
import re
import time
import uuid
from pathlib import Path
from typing import Any

from coraxis.core.logging import get_logger

logger = get_logger("memory")

_SLUG_RE = re.compile(r"[^a-z0-9]+")
#: Chroma collection names are limited and must start/end alphanumerically.
_MAX_SLUG = 40


def slugify_topic(topic: str) -> str:
    """Reduce a free-text topic to a stable, Chroma-safe collection fragment."""
    slug = _SLUG_RE.sub("_", (topic or "").lower()).strip("_")
    return (slug[:_MAX_SLUG] or "general").strip("_")


def collection_name(user_id: str, topic: str) -> str:
    """Namespaced collection name.

    The user prefix is what stops findings leaking between accounts.
    """
    return f"u{user_id[:12]}_{slugify_topic(topic)}"


class VectorStore:
    """Thin async wrapper around a persistent Chroma client."""

    def __init__(self, *, path: str, model_name: str) -> None:
        self.path = Path(path)
        self.model_name = model_name
        self._client: Any | None = None
        self._embedding_fn: Any | None = None
        self._collections: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    # ── Lazy initialisation ──────────────────────────────────────────

    def _ensure_client(self) -> Any:
        """Create the client and embedding function on first use.

        Loading ``all-MiniLM-L6-v2`` costs a second or two and ~90 MB of RAM,
        so it must not happen at import time — only when memory is first used.
        """
        if self._client is None:
            import chromadb
            from chromadb.utils import embedding_functions

            self.path.mkdir(parents=True, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=str(self.path),
                settings=chromadb.Settings(anonymized_telemetry=False),
            )
            self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=self.model_name
            )
            logger.info("vector store initialised at %s", self.path)
        return self._client

    def _collection(self, user_id: str, topic: str) -> Any:
        name = collection_name(user_id, topic)
        if name not in self._collections:
            self._collections[name] = self._ensure_client().get_or_create_collection(
                name=name,
                embedding_function=self._embedding_fn,
                metadata={"topic": topic, "created": time.time()},
            )
        return self._collections[name]

    # ── Writes ───────────────────────────────────────────────────────

    async def upsert(
        self,
        user_id: str,
        topic: str,
        entries: list[dict[str, Any]],
    ) -> list[str]:
        """Store findings. Returns the vector ids written, in input order."""
        usable = [entry for entry in entries if str(entry.get("claim", "")).strip()]
        if not usable:
            return []

        vector_ids = [str(entry.get("vector_id") or uuid.uuid4().hex) for entry in usable]
        for entry, vector_id in zip(usable, vector_ids, strict=True):
            entry["vector_id"] = vector_id

        def _write() -> None:
            collection = self._collection(user_id, topic)
            collection.upsert(
                ids=vector_ids,
                documents=[str(entry["claim"]) for entry in usable],
                metadatas=[self._metadata(entry) for entry in usable],
            )

        async with self._lock:
            try:
                await asyncio.to_thread(_write)
            except Exception:
                logger.exception("failed to write %d findings to memory", len(usable))
                return []

        logger.debug("stored %d findings under topic %r", len(usable), topic)
        return vector_ids

    @staticmethod
    def _metadata(entry: dict[str, Any]) -> dict[str, Any]:
        """Chroma metadata must be scalars — lists are joined."""
        sources = entry.get("sources") or []
        return {
            "topic": str(entry.get("topic", "")),
            "sources": ", ".join(str(source) for source in sources),
            "confidence": float(entry.get("confidence", 0.0)),
            "relevance": float(entry.get("relevance", 0.0)),
            "agent": str(entry.get("agent", "")),
            "timestamp": float(entry.get("timestamp") or time.time()),
        }

    # ── Reads ────────────────────────────────────────────────────────

    async def query(
        self,
        user_id: str,
        topic: str,
        text: str,
        *,
        n_results: int = 5,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        """Find prior findings similar to ``text``.

        Returns an empty list on any failure. Memory is an optimisation; losing
        it should never fail a run.
        """
        if not (text or "").strip():
            return []

        def _read() -> list[dict[str, Any]]:
            collection = self._collection(user_id, topic)
            if collection.count() == 0:
                return []

            raw = collection.query(
                query_texts=[text],
                n_results=min(n_results, max(1, collection.count())),
                include=["documents", "metadatas", "distances"],
            )

            results: list[dict[str, Any]] = []
            ids = raw.get("ids", [[]])[0]
            documents = raw.get("documents", [[]])[0]
            metadatas = raw.get("metadatas", [[]])[0]
            distances = raw.get("distances", [[]])[0]

            for index, vector_id in enumerate(ids):
                metadata = metadatas[index] or {}
                if float(metadata.get("confidence", 0.0)) < min_confidence:
                    continue
                # Chroma returns squared L2 distance; map to a 0-1 similarity.
                distance = distances[index] if index < len(distances) else 1.0
                similarity = max(0.0, 1.0 - min(float(distance), 1.0))
                results.append(
                    {
                        "vector_id": vector_id,
                        "topic": metadata.get("topic", topic),
                        "claim": documents[index] if index < len(documents) else "",
                        "sources": [
                            source
                            for source in str(metadata.get("sources", "")).split(", ")
                            if source
                        ],
                        "confidence": float(metadata.get("confidence", 0.0)),
                        "relevance": float(metadata.get("relevance", 0.0)),
                        "agent": metadata.get("agent", ""),
                        "similarity": round(similarity, 4),
                    }
                )

            results.sort(key=lambda item: item["similarity"], reverse=True)
            return results

        try:
            return await asyncio.to_thread(_read)
        except Exception:
            logger.exception("memory query failed for topic %r", topic)
            return []

    async def list_topics(self, user_id: str) -> list[str]:
        prefix = f"u{user_id[:12]}_"

        def _list() -> list[str]:
            client = self._ensure_client()
            return [
                collection.name
                for collection in client.list_collections()
                if collection.name.startswith(prefix)
            ]

        try:
            return await asyncio.to_thread(_list)
        except Exception:
            logger.exception("failed to list memory collections")
            return []

    async def delete_topic(self, user_id: str, topic: str) -> bool:
        name = collection_name(user_id, topic)

        def _delete() -> bool:
            try:
                self._ensure_client().delete_collection(name=name)
                return True
            except Exception:  # noqa: BLE001 - a missing collection is not an error
                return False

        async with self._lock:
            deleted = await asyncio.to_thread(_delete)
        self._collections.pop(name, None)
        return deleted
