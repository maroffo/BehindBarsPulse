# ABOUTME: Migration to add is_aggregate flag to prison_events table.
# ABOUTME: Separates aggregate statistics from individual events.

"""Add is_aggregate to prison_events

Revision ID: 004
Revises: 003
Create Date: 2026-02-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "004"
down_revision: str | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "prison_events",
        sa.Column("is_aggregate", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.create_index("ix_prison_events_is_aggregate", "prison_events", ["is_aggregate"])


def downgrade() -> None:
    op.drop_index("ix_prison_events_is_aggregate", table_name="prison_events")
    op.drop_column("prison_events", "is_aggregate")
