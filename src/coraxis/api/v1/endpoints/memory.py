"""Semantic memory endpoints.

Reads come from the relational mirror rather than the vector store: listing and
counting are exactly what a database is for, and it keeps the embedding model
out of the request path.
"""

from __future__ import annotations

from fastapi import APIRouter, Query

from coraxis.api.deps import CurrentUser, DbSession, PaginationDep
from coraxis.core.config import get_settings
from coraxis.repositories import memory as memory_repo
from coraxis.schemas.common import DeletedResponse
from coraxis.services.vectorstore import VectorStore

router = APIRouter(prefix="/memory", tags=["memory"])


class MemoryRecordOut(dict):
    """Marker type so the OpenAPI schema is generated for a plain dict payload."""


@router.get("/topics", summary="List memory topics")
async def list_topics(user: CurrentUser, session: DbSession) -> dict:
    """Topics this account has stored findings under."""
    topics = await memory_repo.list_topics(session, user.id)
    return {
        "topics": [
            {
                "topic": entry["topic"],
                "entry_count": entry["entry_count"],
                "last_seen": entry["last_seen"],
            }
            for entry in topics
        ],
        "total_entries": await memory_repo.count(session, user.id),
        "enabled": get_settings().memory_enabled,
    }


@router.get("/records", summary="List stored findings")
async def list_records(
    user: CurrentUser,
    session: DbSession,
    pagination: PaginationDep,
    topic: str | None = Query(default=None),
) -> dict:
    rows, total = await memory_repo.list_records(
        session,
        user.id,
        topic=topic,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    return {
        "items": [
            {
                "id": row.id,
                "topic": row.topic,
                "claim": row.claim,
                "sources": list(row.sources or []),
                "confidence": row.confidence,
                "relevance": row.relevance,
                "agent": row.agent,
                "run_id": row.run_id,
                "created_at": row.created_at.isoformat() + "Z",
            }
            for row in rows
        ],
        "total": total,
        "limit": pagination.limit,
        "offset": pagination.offset,
    }


@router.delete(
    "/topics/{topic}",
    response_model=DeletedResponse,
    summary="Forget a topic",
)
async def delete_topic(topic: str, user: CurrentUser, session: DbSession) -> DeletedResponse:
    """Remove a topic from both the relational mirror and the vector index."""
    removed = await memory_repo.delete_topic(session, user.id, topic)
    await session.commit()

    if get_settings().memory_enabled:
        store = VectorStore(
            path=get_settings().chroma_path, model_name=get_settings().embedding_model
        )
        await store.delete_topic(user.id, topic)

    return DeletedResponse(deleted=removed > 0, id=topic)
