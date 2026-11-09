"""Unit tests for database session scope transaction behavior."""

from __future__ import annotations

import pytest

from coraxis.db.session import session_scope


async def test_session_scope_commits_on_clean_exit(app: object) -> None:
    """Data written inside session_scope is committed on clean exit."""
    from coraxis.repositories import users as user_repo

    async with session_scope() as db_session:
        user = await user_repo.create(
            db_session,
            email="commit-test@example.com",
            password_hash="!test",
            display_name="Commit Test",
        )
        await db_session.flush()
        user_id = user.id

    async with session_scope() as db_session:
        found = await user_repo.get_by_id(db_session, user_id)
    assert found is not None
    assert found.email == "commit-test@example.com"


async def test_session_scope_rolls_back_on_exception(app: object) -> None:
    """Data written inside session_scope is rolled back when an exception occurs."""
    from coraxis.repositories import users as user_repo

    with pytest.raises(ValueError, match="boom"):
        async with session_scope() as db_session:
            user = await user_repo.create(
                db_session,
                email="rollback-test@example.com",
                password_hash="!test",
                display_name="Rollback Test",
            )
            await db_session.flush()
            user_id = user.id
            raise ValueError("boom")

    async with session_scope() as db_session:
        found = await user_repo.get_by_id(db_session, user_id)
    assert found is None
