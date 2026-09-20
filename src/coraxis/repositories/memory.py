"""Semantic memory persistence — the relational half of the memory store.

ChromaDB holds the embeddings; these rows hold the facts. Keeping both means
the vector index can be rebuilt from the database if it is corrupted or the
embedding model is swapped, which would otherwise be silent data loss.
"""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from coraxis.db.models import MemoryRecord
from coraxis.repositories._shared import affected_rows


async def create_records(
    session: AsyncSession,
    user_id: str,
    *,
    run_id: str | None,
    entries: list[dict],
) -> list[MemoryRecord]:
    """Persist a batch of findings. Each entry carries its own ``vector_id``."""
    rows = [
        MemoryRecord(
            user_id=user_id,
            run_id=run_id,
            topic=str(entry.get("topic", ""))[:255],
            claim=str(entry.get("claim", "")),
            sources=list(entry.get("sources", [])),
            confidence=float(entry.get("confidence", 0.0)),
            relevance=float(entry.get("relevance", 0.0)),
            agent=str(entry.get("agent", ""))[:64],
            vector_id=str(entry["vector_id"]) if entry.get("vector_id") else None,
        )
        for entry in entries
        if entry.get("claim")
    ]
    if not rows:
        return []

    session.add_all(rows)
    await session.flush()
    return rows


async def list_records(
    session: AsyncSession,
    user_id: str,
    *,
    topic: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[MemoryRecord], int]:
    filters = [MemoryRecord.user_id == user_id]
    if topic:
        filters.append(MemoryRecord.topic == topic)

    total = await session.execute(select(func.count()).select_from(MemoryRecord).where(*filters))
    result = await session.execute(
        select(MemoryRecord)
        .where(*filters)
        .order_by(MemoryRecord.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), int(total.scalar_one())


async def list_topics(session: AsyncSession, user_id: str) -> list[dict]:
    """Topics with their entry counts, newest activity first."""
    result = await session.execute(
        select(
            MemoryRecord.topic,
            func.count().label("entry_count"),
            func.max(MemoryRecord.created_at).label("last_seen"),
        )
        .where(MemoryRecord.user_id == user_id)
        .group_by(MemoryRecord.topic)
        .order_by(func.max(MemoryRecord.created_at).desc())
    )
    return [
        {"topic": topic, "entry_count": int(count), "last_seen": last_seen}
        for topic, count, last_seen in result.all()
    ]


async def delete_topic(session: AsyncSession, user_id: str, topic: str) -> int:
    result = await session.execute(
        delete(MemoryRecord).where(
            MemoryRecord.user_id == user_id,
            MemoryRecord.topic == topic,
        )
    )
    return affected_rows(result)


async def delete_for_run(session: AsyncSession, run_id: str) -> int:
    result = await session.execute(delete(MemoryRecord).where(MemoryRecord.run_id == run_id))
    return affected_rows(result)


async def count(session: AsyncSession, user_id: str) -> int:
    result = await session.execute(
        select(func.count()).select_from(MemoryRecord).where(MemoryRecord.user_id == user_id)
    )
    return int(result.scalar_one())
