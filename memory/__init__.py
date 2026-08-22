"""
Memory package — ChromaDB embedded client for semantic research memory.
"""

from .chroma_client import (
    ChromaMemory,
    MemoryEntry,
    get_memory,
    remember_findings,
    recall_similar,
    make_memory_entry,
)

__all__ = [
    "ChromaMemory",
    "MemoryEntry",
    "get_memory",
    "remember_findings",
    "recall_similar",
    "make_memory_entry",
]