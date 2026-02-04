# ABOUTME: Pydantic models for bulletin data structures.
# ABOUTME: Defines BulletinContent and Bulletin schemas for AI generation.

from datetime import date

from pydantic import BaseModel


class BulletinContent(BaseModel):
    """AI-generated bulletin content from Gemini."""

    title: str
    subtitle: str
    content: str
    key_topics: list[str]
    sources_cited: list[str]


class Bulletin(BaseModel):
    """Complete bulletin with metadata."""

    issue_date: date
    title: str
    subtitle: str
    content: str
    key_topics: list[str] = []
    sources_cited: list[str] = []
    articles_count: int = 0
    press_review: list[dict] | None = None


class EditorialCommentChunk(BaseModel):
    """A searchable chunk extracted from editorial content."""

    source_type: str
    source_id: int
    source_date: date
    category: str | None
    content: str
