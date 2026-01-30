"""Initial schema with newsletters, articles, narrative tracking, and pgvector.

Revision ID: 001
Revises:
Create Date: 2026-01-30 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # Create importance enum
    importance_enum = postgresql.ENUM("Alta", "Media", "Bassa", name="importance_enum")
    importance_enum.create(op.get_bind(), checkfirst=True)

    # Create story status enum
    story_status_enum = postgresql.ENUM("active", "dormant", "resolved", name="story_status_enum")
    story_status_enum.create(op.get_bind(), checkfirst=True)

    # Create newsletters table
    op.create_table(
        "newsletters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("subtitle", sa.String(length=1000), nullable=False),
        sa.Column("opening", sa.Text(), nullable=False),
        sa.Column("closing", sa.Text(), nullable=False),
        sa.Column("html_content", sa.Text(), nullable=True),
        sa.Column("txt_content", sa.Text(), nullable=True),
        sa.Column("press_review", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("issue_date"),
    )
    op.create_index("ix_newsletters_issue_date", "newsletters", ["issue_date"], unique=False)
    op.create_index(
        "ix_newsletters_issue_date_desc",
        "newsletters",
        [sa.text("issue_date DESC")],
        unique=False,
    )

    # Create articles table
    op.create_table(
        "articles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(length=1000), nullable=False),
        sa.Column("link", sa.String(length=2000), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author", sa.String(length=500), nullable=True),
        sa.Column("source", sa.String(length=500), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("category", sa.String(length=200), nullable=True),
        sa.Column(
            "importance",
            sa.Enum("Alta", "Media", "Bassa", name="importance_enum"),
            nullable=True,
        ),
        sa.Column("published_date", sa.Date(), nullable=True),
        sa.Column("wayback_url", sa.String(length=2000), nullable=True),
        sa.Column("embedding", Vector(768), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("newsletter_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["newsletter_id"], ["newsletters.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("link"),
    )
    op.create_index("ix_articles_published_date", "articles", ["published_date"], unique=False)
    op.create_index(
        "ix_articles_published_date_desc",
        "articles",
        [sa.text("published_date DESC")],
        unique=False,
    )

    # Create story_threads table
    op.create_table(
        "story_threads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("topic", sa.String(length=500), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "dormant", "resolved", name="story_status_enum"),
            nullable=False,
        ),
        sa.Column("first_seen", sa.Date(), nullable=False),
        sa.Column("last_update", sa.Date(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("related_articles", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("mention_count", sa.Integer(), nullable=False),
        sa.Column("impact_score", sa.Float(), nullable=False),
        sa.Column("weekly_highlight", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_story_threads_status", "story_threads", ["status"], unique=False)

    # Create key_characters table
    op.create_table(
        "key_characters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("role", sa.String(length=500), nullable=False),
        sa.Column("aliases", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # Create character_positions table
    op.create_table(
        "character_positions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("position_date", sa.Date(), nullable=False),
        sa.Column("stance", sa.Text(), nullable=False),
        sa.Column("source_url", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["character_id"], ["key_characters.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "character_id", "position_date", "stance", name="uq_character_position"
        ),
    )

    # Create followups table
    op.create_table(
        "followups",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("event", sa.Text(), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=False),
        sa.Column("story_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.Date(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["story_id"], ["story_threads.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_followups_expected_date", "followups", ["expected_date"], unique=False)

    # Create vector similarity index (IVFFlat) for embeddings
    # Note: This should be created after data is loaded for optimal performance
    # For now, we create it with a small list count; consider rebuilding with more data
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_articles_embedding ON articles
        USING ivfflat (embedding vector_cosine_ops)
        WITH (lists = 100)
        """
    )


def downgrade() -> None:
    op.drop_index("ix_articles_embedding", table_name="articles")
    op.drop_table("followups")
    op.drop_table("character_positions")
    op.drop_table("key_characters")
    op.drop_table("story_threads")
    op.drop_table("articles")
    op.drop_index("ix_newsletters_issue_date_desc", table_name="newsletters")
    op.drop_index("ix_newsletters_issue_date", table_name="newsletters")
    op.drop_table("newsletters")

    # Drop enums
    op.execute("DROP TYPE IF EXISTS importance_enum")
    op.execute("DROP TYPE IF EXISTS story_status_enum")
