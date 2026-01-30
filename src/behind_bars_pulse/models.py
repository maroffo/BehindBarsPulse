# ABOUTME: Pydantic models for newsletter data structures.
# ABOUTME: Defines Article, NewsletterContent, and PressReview schemas.

from datetime import date
from enum import Enum

from pydantic import BaseModel, HttpUrl


class Importance(str, Enum):
    """Article importance ranking."""

    ALTA = "Alta"
    MEDIA = "Media"
    BASSA = "Bassa"


class Article(BaseModel):
    """Raw article from RSS feed."""

    title: str
    link: HttpUrl
    content: str


class ArticleInfo(BaseModel):
    """Extracted article metadata from AI."""

    author: str
    source: str
    summary: str


class EnrichedArticle(Article):
    """Article with AI-extracted metadata."""

    author: str = ""
    source: str = ""
    summary: str = ""
    published_date: date | None = None


class PressReviewArticle(BaseModel):
    """Article reference in press review."""

    title: str
    link: HttpUrl
    importance: Importance
    author: str = ""
    source: str = ""
    summary: str = ""
    published_date: date | None = None


class PressReviewCategory(BaseModel):
    """Category grouping in press review."""

    category: str
    comment: str
    articles: list[PressReviewArticle]


class PressReview(BaseModel):
    """Complete press review with categorized articles."""

    categories: list[PressReviewCategory]


class NewsletterContent(BaseModel):
    """AI-generated newsletter content."""

    title: str
    subtitle: str
    opening: str
    closing: str


class NewsletterContext(BaseModel):
    """Complete context for newsletter rendering."""

    subject: str
    today_str: str
    newsletter_title: str
    newsletter_subtitle: str
    newsletter_opening: str
    newsletter_closing: str
    press_review: list[PressReviewCategory]
    notification_address_list: list[str] = []
