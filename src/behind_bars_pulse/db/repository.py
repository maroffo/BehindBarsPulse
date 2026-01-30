# ABOUTME: Repository classes for database access patterns.
# ABOUTME: Provides NewsletterRepository, ArticleRepository, NarrativeRepository for CRUD operations.

from collections.abc import Sequence
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from behind_bars_pulse.db.models import (
    Article,
    CharacterPosition,
    FollowUp,
    KeyCharacter,
    Newsletter,
    StoryThread,
)


class NewsletterRepository:
    """Repository for Newsletter CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, newsletter: Newsletter) -> Newsletter:
        """Save a newsletter (insert or update)."""
        self.session.add(newsletter)
        await self.session.flush()
        return newsletter

    async def get_by_id(self, newsletter_id: int) -> Newsletter | None:
        """Get newsletter by ID."""
        return await self.session.get(Newsletter, newsletter_id)

    async def get_by_date(self, issue_date: date) -> Newsletter | None:
        """Get newsletter by issue date."""
        result = await self.session.execute(
            select(Newsletter).where(Newsletter.issue_date == issue_date)
        )
        return result.scalar_one_or_none()

    async def list_recent(self, limit: int = 10, offset: int = 0) -> Sequence[Newsletter]:
        """List recent newsletters ordered by date descending."""
        result = await self.session.execute(
            select(Newsletter).order_by(Newsletter.issue_date.desc()).limit(limit).offset(offset)
        )
        return result.scalars().all()

    async def count(self) -> int:
        """Count total newsletters."""
        result = await self.session.execute(select(func.count(Newsletter.id)))
        return result.scalar_one()

    async def delete_by_date(self, issue_date: date) -> bool:
        """Delete newsletter by date. Returns True if deleted."""
        result = await self.session.execute(
            delete(Newsletter).where(Newsletter.issue_date == issue_date)
        )
        return result.rowcount > 0


class ArticleRepository:
    """Repository for Article CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, article: Article) -> Article:
        """Save an article (insert or update)."""
        self.session.add(article)
        await self.session.flush()
        return article

    async def save_batch(self, articles: list[Article]) -> list[Article]:
        """Save multiple articles in batch."""
        self.session.add_all(articles)
        await self.session.flush()
        return articles

    async def get_by_id(self, article_id: int) -> Article | None:
        """Get article by ID."""
        return await self.session.get(Article, article_id)

    async def get_by_link(self, link: str) -> Article | None:
        """Get article by URL."""
        result = await self.session.execute(select(Article).where(Article.link == link))
        return result.scalar_one_or_none()

    async def list_by_newsletter(self, newsletter_id: int) -> Sequence[Article]:
        """List articles belonging to a newsletter."""
        result = await self.session.execute(
            select(Article)
            .where(Article.newsletter_id == newsletter_id)
            .order_by(Article.category, Article.importance.desc())
        )
        return result.scalars().all()

    async def list_recent(
        self, limit: int = 20, offset: int = 0, category: str | None = None
    ) -> Sequence[Article]:
        """List recent articles, optionally filtered by category."""
        query = select(Article).order_by(Article.published_date.desc().nulls_last())
        if category:
            query = query.where(Article.category == category)
        query = query.limit(limit).offset(offset)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def search_by_embedding(
        self, embedding: list[float], limit: int = 10, threshold: float = 0.7
    ) -> Sequence[tuple[Article, float]]:
        """Search articles by embedding similarity (cosine distance).

        Args:
            embedding: Query embedding vector
            limit: Maximum results to return
            threshold: Minimum similarity threshold (0-1, higher = more similar)

        Returns:
            List of (Article, similarity_score) tuples
        """
        # Cosine distance: lower = more similar, so 1 - distance = similarity
        distance = Article.embedding.cosine_distance(embedding)
        result = await self.session.execute(
            select(Article, (1 - distance).label("similarity"))
            .where(Article.embedding.isnot(None))
            .where((1 - distance) >= threshold)
            .order_by(distance)
            .limit(limit)
        )
        return [(row.Article, row.similarity) for row in result.all()]

    async def count(self, category: str | None = None) -> int:
        """Count total articles, optionally filtered by category."""
        query = select(func.count(Article.id))
        if category:
            query = query.where(Article.category == category)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def list_categories(self) -> Sequence[str]:
        """List all distinct categories."""
        result = await self.session.execute(
            select(Article.category)
            .where(Article.category.isnot(None))
            .distinct()
            .order_by(Article.category)
        )
        return result.scalars().all()


class NarrativeRepository:
    """Repository for narrative tracking (stories, characters, followups)."""

    def __init__(self, session: AsyncSession):
        self.session = session

    # Story threads

    async def save_story(self, story: StoryThread) -> StoryThread:
        """Save a story thread."""
        self.session.add(story)
        await self.session.flush()
        return story

    async def get_story_by_id(self, story_id: str) -> StoryThread | None:
        """Get story by ID."""
        return await self.session.get(StoryThread, story_id)

    async def list_active_stories(self) -> Sequence[StoryThread]:
        """List active story threads."""
        result = await self.session.execute(
            select(StoryThread)
            .where(StoryThread.status == "active")
            .order_by(StoryThread.impact_score.desc(), StoryThread.last_update.desc())
        )
        return result.scalars().all()

    async def list_stories_by_status(self, status: str) -> Sequence[StoryThread]:
        """List stories by status."""
        result = await self.session.execute(
            select(StoryThread)
            .where(StoryThread.status == status)
            .order_by(StoryThread.last_update.desc())
        )
        return result.scalars().all()

    async def search_stories_by_keyword(self, keyword: str) -> Sequence[StoryThread]:
        """Search stories by keyword match in topic or keywords array."""
        keyword_lower = keyword.lower()
        result = await self.session.execute(
            select(StoryThread).where(
                StoryThread.topic.ilike(f"%{keyword_lower}%")
                # JSONB array search handled with containment check
            )
        )
        return result.scalars().all()

    # Key characters

    async def save_character(self, character: KeyCharacter) -> KeyCharacter:
        """Save a key character."""
        self.session.add(character)
        await self.session.flush()
        return character

    async def get_character_by_name(self, name: str) -> KeyCharacter | None:
        """Get character by name (exact match)."""
        result = await self.session.execute(select(KeyCharacter).where(KeyCharacter.name == name))
        return result.scalar_one_or_none()

    async def list_characters(self) -> Sequence[KeyCharacter]:
        """List all key characters."""
        result = await self.session.execute(select(KeyCharacter).order_by(KeyCharacter.name))
        return result.scalars().all()

    async def save_position(self, position: CharacterPosition) -> CharacterPosition:
        """Save a character position."""
        self.session.add(position)
        await self.session.flush()
        return position

    # Follow-ups

    async def save_followup(self, followup: FollowUp) -> FollowUp:
        """Save a follow-up event."""
        self.session.add(followup)
        await self.session.flush()
        return followup

    async def get_followup_by_id(self, followup_id: str) -> FollowUp | None:
        """Get follow-up by ID."""
        return await self.session.get(FollowUp, followup_id)

    async def list_pending_followups(self) -> Sequence[FollowUp]:
        """List pending (unresolved) follow-ups."""
        result = await self.session.execute(
            select(FollowUp)
            .where(FollowUp.resolved == False)  # noqa: E712
            .order_by(FollowUp.expected_date)
        )
        return result.scalars().all()

    async def list_due_followups(self, as_of: date) -> Sequence[FollowUp]:
        """List follow-ups due on or before the given date."""
        result = await self.session.execute(
            select(FollowUp)
            .where(FollowUp.resolved == False)  # noqa: E712
            .where(FollowUp.expected_date <= as_of)
            .order_by(FollowUp.expected_date)
        )
        return result.scalars().all()

    async def resolve_followup(self, followup_id: str) -> bool:
        """Mark a follow-up as resolved. Returns True if found."""
        followup = await self.get_followup_by_id(followup_id)
        if followup:
            followup.resolved = True
            return True
        return False
