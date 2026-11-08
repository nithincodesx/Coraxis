"""Add custom_provider_nickname to agent_llm_settings.

Lets an agent point at a named custom OpenAI-compatible provider (from the
custom_providers table) instead of only at a generic base URL. Empty means the
agent uses its own base_url / model columns, so existing settings keep working.

Revision ID: f7e8d9c0b1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-11-08 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7e8d9c0b1a2"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_llm_settings",
        sa.Column(
            "custom_provider_nickname",
            sa.String(length=80),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("agent_llm_settings", "custom_provider_nickname")
