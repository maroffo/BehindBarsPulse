# ABOUTME: Migration to add facility_snapshots table for capacity tracking.
# ABOUTME: Enables tracking occupancy rates and inmate counts over time.

"""Add facility_snapshots table

Revision ID: 005
Revises: 004
Create Date: 2026-02-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "facility_snapshots",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("facility", sa.String(200), nullable=False),
        sa.Column("region", sa.String(100), nullable=True),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("inmates", sa.Integer(), nullable=True),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("occupancy_rate", sa.Float(), nullable=True),
        sa.Column("source_url", sa.String(2000), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=True),
        sa.Column("extracted_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("facility", "snapshot_date", "source_url", name="uq_facility_snapshot"),
    )
    op.create_index("ix_facility_snapshots_facility", "facility_snapshots", ["facility"])
    op.create_index("ix_facility_snapshots_region", "facility_snapshots", ["region"])
    op.create_index(
        "ix_facility_snapshots_date", "facility_snapshots", [sa.text("snapshot_date DESC")]
    )


def downgrade() -> None:
    op.drop_index("ix_facility_snapshots_date", table_name="facility_snapshots")
    op.drop_index("ix_facility_snapshots_region", table_name="facility_snapshots")
    op.drop_index("ix_facility_snapshots_facility", table_name="facility_snapshots")
    op.drop_table("facility_snapshots")
