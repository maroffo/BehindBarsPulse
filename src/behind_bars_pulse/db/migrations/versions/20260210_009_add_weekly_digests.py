# ABOUTME: Add weekly_digests table for storing weekly digest summaries.
# ABOUTME: Stores narrative arcs, reflections, and upcoming events per week.

"""Add weekly_digests table.

Revision ID: 009
Revises: 008
Create Date: 2026-02-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers
revision: str = "009"
down_revision: str | None = "008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "weekly_digests",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("week_start", sa.Date, nullable=False),
        sa.Column("week_end", sa.Date, nullable=False, unique=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("subtitle", sa.String(500), nullable=True),
        sa.Column("narrative_arcs", JSONB, nullable=True),
        sa.Column("weekly_reflection", sa.Text, nullable=True),
        sa.Column("upcoming_events", JSONB, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_weekly_digests_week_end", "weekly_digests", ["week_end"])
    op.create_index(
        "ix_weekly_digests_week_end_desc",
        "weekly_digests",
        [sa.text("week_end DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_weekly_digests_week_end_desc")
    op.drop_index("ix_weekly_digests_week_end")
    op.drop_table("weekly_digests")
