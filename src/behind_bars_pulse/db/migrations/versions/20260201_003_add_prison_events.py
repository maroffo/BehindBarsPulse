"""Add prison_events table for structured event extraction.

Revision ID: 003
Revises: 002
Create Date: 2026-02-01 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prison_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=True),
        sa.Column("facility", sa.String(length=200), nullable=True),
        sa.Column("region", sa.String(length=100), nullable=True),
        sa.Column("count", sa.Integer(), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=2000), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("extracted_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prison_events_event_type", "prison_events", ["event_type"])
    op.create_index("ix_prison_events_event_date", "prison_events", [sa.text("event_date DESC")])
    op.create_index("ix_prison_events_facility", "prison_events", ["facility"])
    op.create_index("ix_prison_events_region", "prison_events", ["region"])


def downgrade() -> None:
    op.drop_index("ix_prison_events_region", table_name="prison_events")
    op.drop_index("ix_prison_events_facility", table_name="prison_events")
    op.drop_index("ix_prison_events_event_date", table_name="prison_events")
    op.drop_index("ix_prison_events_event_type", table_name="prison_events")
    op.drop_table("prison_events")
