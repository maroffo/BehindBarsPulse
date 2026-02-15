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
    # Use IF NOT EXISTS to handle table already created outside Alembic
    op.execute("""
        CREATE TABLE IF NOT EXISTS weekly_digests (
            id SERIAL PRIMARY KEY,
            week_start DATE NOT NULL,
            week_end DATE NOT NULL UNIQUE,
            title VARCHAR(500) NOT NULL,
            subtitle VARCHAR(500),
            narrative_arcs JSONB,
            weekly_reflection TEXT,
            upcoming_events JSONB,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_weekly_digests_week_end
        ON weekly_digests (week_end)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_weekly_digests_week_end_desc
        ON weekly_digests (week_end DESC)
    """)


def downgrade() -> None:
    op.drop_index("ix_weekly_digests_week_end_desc")
    op.drop_index("ix_weekly_digests_week_end")
    op.drop_table("weekly_digests")
