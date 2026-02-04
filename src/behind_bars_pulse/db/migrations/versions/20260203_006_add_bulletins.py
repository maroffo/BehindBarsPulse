# ABOUTME: Migration to add bulletins and editorial_comments tables.
# ABOUTME: Enables daily editorial bulletins and searchable editorial content.

"""Add bulletins and editorial_comments tables

Revision ID: 006
Revises: 005
Create Date: 2026-02-03

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSION = 768


def upgrade() -> None:
    # Bulletins table - daily editorial commentary
    op.create_table(
        "bulletins",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("subtitle", sa.String(500), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=True),
        sa.Column("articles_count", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issue_date", name="uq_bulletins_issue_date"),
    )
    op.create_index("ix_bulletins_issue_date", "bulletins", ["issue_date"])
    op.create_index(
        "ix_bulletins_issue_date_desc", "bulletins", [sa.text("issue_date DESC")]
    )
    op.create_index(
        "ix_bulletins_embedding",
        "bulletins",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )

    # Editorial comments table - extracted searchable chunks
    op.create_table(
        "editorial_comments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_date", sa.Date(), nullable=False),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(EMBEDDING_DIMENSION), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_editorial_comments_source_type", "editorial_comments", ["source_type"])
    op.create_index("ix_editorial_comments_source_date", "editorial_comments", ["source_date"])
    op.create_index(
        "ix_editorial_comments_source_date_desc",
        "editorial_comments",
        [sa.text("source_date DESC")],
    )
    op.create_index(
        "ix_editorial_comments_embedding",
        "editorial_comments",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_editorial_comments_embedding", table_name="editorial_comments")
    op.drop_index("ix_editorial_comments_source_date_desc", table_name="editorial_comments")
    op.drop_index("ix_editorial_comments_source_date", table_name="editorial_comments")
    op.drop_index("ix_editorial_comments_source_type", table_name="editorial_comments")
    op.drop_table("editorial_comments")

    op.drop_index("ix_bulletins_embedding", table_name="bulletins")
    op.drop_index("ix_bulletins_issue_date_desc", table_name="bulletins")
    op.drop_index("ix_bulletins_issue_date", table_name="bulletins")
    op.drop_table("bulletins")
