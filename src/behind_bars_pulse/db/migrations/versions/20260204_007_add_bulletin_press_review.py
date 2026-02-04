# ABOUTME: Migration to add press_review JSONB column to bulletins.
# ABOUTME: Stores AI-generated thematic categories with editorial comments.

"""Add press_review to bulletins

Revision ID: 007
Revises: 006
Create Date: 2026-02-04

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "007"
down_revision: str | None = "006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("bulletins", sa.Column("press_review", JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column("bulletins", "press_review")
