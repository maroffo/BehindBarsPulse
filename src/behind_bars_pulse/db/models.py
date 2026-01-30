# ABOUTME: SQLAlchemy ORM models for newsletter database persistence.
# ABOUTME: Defines Newsletter, Article, StoryThread, KeyCharacter, FollowUp tables with pgvector support.

from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

if TYPE_CHECKING:
    pass

EMBEDDING_DIMENSION = 768  # text-multilingual-embedding-002


class Base(DeclarativeBase):
    """Base class for all ORM models."""

    pass


class Newsletter(Base):
    """A daily newsletter issue with generated content and press review."""

    __tablename__ = "newsletters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    subtitle: Mapped[str] = mapped_column(String(1000), nullable=False)
    opening: Mapped[str] = mapped_column(Text, nullable=False)
    closing: Mapped[str] = mapped_column(Text, nullable=False)
    html_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    txt_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    press_review: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    articles: Mapped[list["Article"]] = relationship(
        "Article", back_populates="newsletter", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_newsletters_issue_date_desc", issue_date.desc()),)

    def __repr__(self) -> str:
        return f"<Newsletter {self.issue_date}: {self.title[:50]}...>"


class Article(Base):
    """An article included in a newsletter with AI-generated metadata and embedding."""

    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    link: Mapped[str] = mapped_column(String(2000), nullable=False, unique=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(String(500), nullable=True)
    source: Mapped[str | None] = mapped_column(String(500), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str | None] = mapped_column(String(200), nullable=True)
    importance: Mapped[str | None] = mapped_column(
        Enum("Alta", "Media", "Bassa", name="importance_enum"), nullable=True
    )
    published_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    wayback_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(EMBEDDING_DIMENSION), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    newsletter_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("newsletters.id", ondelete="SET NULL"), nullable=True
    )
    newsletter: Mapped[Newsletter | None] = relationship("Newsletter", back_populates="articles")

    __table_args__ = (
        Index("ix_articles_published_date_desc", published_date.desc()),
        Index(
            "ix_articles_embedding",
            embedding,
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    def __repr__(self) -> str:
        return f"<Article {self.id}: {self.title[:50]}...>"


class StoryThread(Base):
    """An ongoing story thread being tracked across newsletters."""

    __tablename__ = "story_threads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("active", "dormant", "resolved", name="story_status_enum"),
        nullable=False,
        default="active",
    )
    first_seen: Mapped[date] = mapped_column(Date, nullable=False)
    last_update: Mapped[date] = mapped_column(Date, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    related_articles: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    mention_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    impact_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    weekly_highlight: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    followups: Mapped[list["FollowUp"]] = relationship(
        "FollowUp", back_populates="story", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_story_threads_status", "status"),)

    def __repr__(self) -> str:
        return f"<StoryThread {self.id[:8]}: {self.topic[:40]}...>"


class KeyCharacter(Base):
    """A key figure in the Italian prison/justice system being tracked."""

    __tablename__ = "key_characters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    role: Mapped[str] = mapped_column(String(500), nullable=False)
    aliases: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    positions: Mapped[list["CharacterPosition"]] = relationship(
        "CharacterPosition", back_populates="character", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<KeyCharacter {self.name}>"


class CharacterPosition(Base):
    """A recorded position or stance by a key character on a specific date."""

    __tablename__ = "character_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    character_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("key_characters.id", ondelete="CASCADE"), nullable=False
    )
    position_date: Mapped[date] = mapped_column(Date, nullable=False)
    stance: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    character: Mapped[KeyCharacter] = relationship("KeyCharacter", back_populates="positions")

    __table_args__ = (
        UniqueConstraint("character_id", "position_date", "stance", name="uq_character_position"),
    )

    def __repr__(self) -> str:
        return f"<CharacterPosition {self.character_id} @ {self.position_date}>"


class FollowUp(Base):
    """An upcoming event or deadline to track and reference."""

    __tablename__ = "followups"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    event: Mapped[str] = mapped_column(Text, nullable=False)
    expected_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    story_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("story_threads.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[date] = mapped_column(Date, nullable=False)
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    story: Mapped[StoryThread | None] = relationship("StoryThread", back_populates="followups")

    __table_args__ = (Index("ix_followups_expected_date", expected_date),)

    def __repr__(self) -> str:
        return f"<FollowUp {self.id[:8]}: {self.event[:40]}...>"
