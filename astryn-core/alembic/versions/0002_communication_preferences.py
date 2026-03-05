"""Add communication_preferences table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-04
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "communication_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("sessions.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("verbosity", sa.String(), nullable=False, server_default="balanced"),
        sa.Column("tone", sa.String(), nullable=False, server_default="casual"),
        sa.Column("code_explanation", sa.String(), nullable=False, server_default="explain"),
        sa.Column("proactive_suggestions", sa.Boolean(), nullable=False, server_default="true"),
    )


def downgrade() -> None:
    op.drop_table("communication_preferences")
