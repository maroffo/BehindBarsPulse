"""Add subscribers table for newsletter subscriptions.

Revision ID: 002
Revises: 001
Create Date: 2026-02-01 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "subscribers",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("subscribed_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("unsubscribed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_subscribers_email", "subscribers", ["email"], unique=False)
    op.create_index("ix_subscribers_token", "subscribers", ["token"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_subscribers_token", table_name="subscribers")
    op.drop_index("ix_subscribers_email", table_name="subscribers")
    op.drop_table("subscribers")
