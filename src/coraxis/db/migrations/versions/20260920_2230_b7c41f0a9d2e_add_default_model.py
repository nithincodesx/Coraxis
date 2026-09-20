"""Add provider_credentials.default_model.

Lets a user pin the model for a provider instead of relying on the built-in
default, which goes stale as providers retire ids. Empty means "use the
default", so existing rows keep working unchanged.

Revision ID: 20260920_2230_b7c41f0a9d2e
Revises: 20260916_2203_e34d49dca110
Create Date: 2026-09-20 22:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c41f0a9d2e"
down_revision: str | None = "e34d49dca110"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # server_default is required: the column is NOT NULL and existing rows need
    # a value. It is kept rather than dropped so a downgrade/upgrade cycle on a
    # populated table does not fail.
    op.add_column(
        "provider_credentials",
        sa.Column(
            "default_model",
            sa.String(length=160),
            nullable=False,
            server_default="",
        ),
    )


def downgrade() -> None:
    op.drop_column("provider_credentials", "default_model")
