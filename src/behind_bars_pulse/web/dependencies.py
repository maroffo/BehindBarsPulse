# ABOUTME: FastAPI dependency injection for database sessions and services.
# ABOUTME: Provides reusable dependencies for route handlers.

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from behind_bars_pulse.db.repository import (
    ArticleRepository,
    BulletinRepository,
    EditorialCommentRepository,
    NarrativeRepository,
    NewsletterRepository,
    WeeklyDigestRepository,
)
from behind_bars_pulse.db.session import get_db_session
from behind_bars_pulse.services.embedding_service import EmbeddingService

# Type aliases for common dependencies
DbSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_templates(request: Request) -> Jinja2Templates:
    """Get Jinja2 templates from app state."""
    return request.app.state.templates


Templates = Annotated[Jinja2Templates, Depends(get_templates)]


async def get_newsletter_repository(
    session: DbSession,
) -> AsyncGenerator[NewsletterRepository]:
    """Get newsletter repository with session."""
    yield NewsletterRepository(session)


NewsletterRepo = Annotated[NewsletterRepository, Depends(get_newsletter_repository)]


async def get_article_repository(
    session: DbSession,
) -> AsyncGenerator[ArticleRepository]:
    """Get article repository with session."""
    yield ArticleRepository(session)


ArticleRepo = Annotated[ArticleRepository, Depends(get_article_repository)]


async def get_narrative_repository(
    session: DbSession,
) -> AsyncGenerator[NarrativeRepository]:
    """Get narrative repository with session."""
    yield NarrativeRepository(session)


NarrativeRepo = Annotated[NarrativeRepository, Depends(get_narrative_repository)]


def get_embedding_service() -> EmbeddingService:
    """Get embedding service instance."""
    return EmbeddingService()


EmbeddingSvc = Annotated[EmbeddingService, Depends(get_embedding_service)]


async def get_bulletin_repository(
    session: DbSession,
) -> AsyncGenerator[BulletinRepository]:
    """Get bulletin repository with session."""
    yield BulletinRepository(session)


BulletinRepo = Annotated[BulletinRepository, Depends(get_bulletin_repository)]


async def get_editorial_comment_repository(
    session: DbSession,
) -> AsyncGenerator[EditorialCommentRepository]:
    """Get editorial comment repository with session."""
    yield EditorialCommentRepository(session)


EditorialCommentRepo = Annotated[
    EditorialCommentRepository, Depends(get_editorial_comment_repository)
]


async def get_weekly_digest_repository(
    session: DbSession,
) -> AsyncGenerator[WeeklyDigestRepository]:
    """Get weekly digest repository with session."""
    yield WeeklyDigestRepository(session)


WeeklyDigestRepo = Annotated[WeeklyDigestRepository, Depends(get_weekly_digest_repository)]
