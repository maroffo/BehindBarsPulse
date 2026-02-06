# ABOUTME: Add timezone support to all datetime columns.
# ABOUTME: Converts TIMESTAMP WITHOUT TIME ZONE to TIMESTAMP WITH TIME ZONE.

"""Add timezone to datetime columns.

Revision ID: 008
Revises: 007
Create Date: 2026-02-05
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None

# All datetime columns that need timezone support
COLUMNS_TO_MIGRATE = [
    ("newsletters", "created_at"),
    ("articles", "created_at"),
    ("story_threads", "created_at"),
    ("key_characters", "created_at"),
    ("character_positions", "created_at"),
    ("subscribers", "subscribed_at"),
    ("subscribers", "confirmed_at"),
    ("subscribers", "unsubscribed_at"),
    ("prison_events", "extracted_at"),
    ("facility_snapshots", "extracted_at"),
    ("bulletins", "created_at"),
    ("editorial_comments", "created_at"),
]


def upgrade() -> None:
    for table, column in COLUMNS_TO_MIGRATE:
        # Convert existing timestamps assuming they're UTC
        op.execute(
            f"ALTER TABLE {table} "
            f"ALTER COLUMN {column} TYPE TIMESTAMPTZ "
            f"USING {column} AT TIME ZONE 'UTC'"
        )


def downgrade() -> None:
    for table, column in COLUMNS_TO_MIGRATE:
        # Convert back to naive timestamps (loses timezone info)
        op.execute(
            f"ALTER TABLE {table} "
            f"ALTER COLUMN {column} TYPE TIMESTAMP WITHOUT TIME ZONE"
        )
