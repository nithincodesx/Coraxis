"""Add custom_providers for multiple OpenAI-compatible endpoints per user.

A user can now store several named custom providers (Inception, Together,
OpenRouter, a local vLLM, ...) each with its own base URL, model, and encrypted
key. The generic ``provider_credentials.custom`` row remains as a single
fallback; named providers win when referenced by nickname.

Revision ID: a1b2c3d4e5f6
Revises: b7c41f0a9d2e
Create Date: 2026-11-08 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "b7c41f0a9d2e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "custom_providers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("nickname", sa.String(length=80), nullable=False),
        sa.Column("base_url", sa.String(length=255), nullable=False),
        sa.Column("model", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("encrypted_key", sa.Text(), nullable=False, server_default=""),
        sa.Column("key_hint", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_validated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "last_validation_error",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_custom_providers_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_providers")),
        sa.UniqueConstraint(
            "user_id",
            "nickname",
            name="uq_custom_providers_user_nickname",
        ),
    )
    op.create_index(
        op.f("ix_custom_providers_created_at"),
        "custom_providers",
        ["created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_custom_providers_created_at"), table_name="custom_providers")
    op.drop_table("custom_providers")
