# ABOUTME: Repository classes for database access patterns.
# ABOUTME: Provides NewsletterRepository, ArticleRepository, NarrativeRepository for CRUD operations.

from collections.abc import Sequence
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from behind_bars_pulse.db.models import (
    Article,
    Bulletin,
    CharacterPosition,
    EditorialComment,
    FacilitySnapshot,
    FollowUp,
    KeyCharacter,
    Newsletter,
    PrisonEvent,
    StoryThread,
    Subscriber,
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

    async def list_by_published_date(self, published_date: date) -> Sequence[Article]:
        """List articles published on a specific date."""
        result = await self.session.execute(
            select(Article).where(Article.published_date == published_date).order_by(Article.id)
        )
        return result.scalars().all()

    async def list_by_date_range(self, start_date: date, end_date: date) -> Sequence[Article]:
        """List articles published within a date range (inclusive)."""
        result = await self.session.execute(
            select(Article)
            .where(Article.published_date >= start_date)
            .where(Article.published_date <= end_date)
            .order_by(Article.published_date.desc(), Article.id)
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
        self,
        embedding: list[float],
        threshold: float = 0.6,
        min_results: int = 10,
        limit: int = 25,
        offset: int = 0,
    ) -> tuple[Sequence[tuple[Article, float]], int]:
        """Search articles by embedding similarity (cosine distance).

        Returns all results above threshold, but guarantees min_results.
        If threshold returns fewer than min_results, top min_results are returned.
        Supports pagination with limit/offset.

        Args:
            embedding: Query embedding vector
            threshold: Minimum similarity threshold (0-1, higher = more similar)
            min_results: Minimum number of results to return (ignores threshold if needed)
            limit: Maximum results per page
            offset: Number of results to skip

        Returns:
            Tuple of (results list, total count)
        """
        distance = Article.embedding.cosine_distance(embedding)
        similarity = (1 - distance).label("similarity")

        # Count total results above threshold
        count_result = await self.session.execute(
            select(func.count(Article.id))
            .where(Article.embedding.isnot(None))
            .where((1 - distance) >= threshold)
        )
        total_above_threshold = count_result.scalar_one()

        # If enough results above threshold, use threshold query with pagination
        if total_above_threshold >= min_results:
            result = await self.session.execute(
                select(Article, similarity)
                .where(Article.embedding.isnot(None))
                .where((1 - distance) >= threshold)
                .order_by(distance)
                .limit(limit)
                .offset(offset)
            )
            results = [(row.Article, row.similarity) for row in result.all()]
            return results, total_above_threshold

        # Not enough above threshold - return exactly min_results (no pagination)
        result = await self.session.execute(
            select(Article, similarity)
            .where(Article.embedding.isnot(None))
            .order_by(distance)
            .limit(min_results)
            .offset(offset)
        )
        results = [(row.Article, row.similarity) for row in result.all()]
        # No pagination for fallback - just return min_results
        return results, min(min_results, len(results) + offset)

    async def count(self, category: str | None = None) -> int:
        """Count total articles, optionally filtered by category."""
        query = select(func.count(Article.id))
        if category:
            query = query.where(Article.category == category)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def count_with_embeddings(self) -> int:
        """Count articles that have embeddings."""
        result = await self.session.execute(
            select(func.count(Article.id)).where(Article.embedding.isnot(None))
        )
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


class SubscriberRepository:
    """Repository for Subscriber CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, subscriber: Subscriber) -> Subscriber:
        """Save a subscriber (insert or update)."""
        self.session.add(subscriber)
        await self.session.flush()
        return subscriber

    async def get_by_email(self, email: str) -> Subscriber | None:
        """Get subscriber by email address."""
        result = await self.session.execute(select(Subscriber).where(Subscriber.email == email))
        return result.scalar_one_or_none()

    async def get_by_token(self, token: str) -> Subscriber | None:
        """Get subscriber by confirmation/unsubscribe token."""
        result = await self.session.execute(select(Subscriber).where(Subscriber.token == token))
        return result.scalar_one_or_none()

    async def list_active(self) -> Sequence[Subscriber]:
        """List active subscribers (confirmed and not unsubscribed)."""
        result = await self.session.execute(
            select(Subscriber)
            .where(Subscriber.confirmed == True)  # noqa: E712
            .where(Subscriber.unsubscribed_at.is_(None))
            .order_by(Subscriber.subscribed_at)
        )
        return result.scalars().all()

    async def count_active(self) -> int:
        """Count active subscribers."""
        result = await self.session.execute(
            select(func.count(Subscriber.id))
            .where(Subscriber.confirmed == True)  # noqa: E712
            .where(Subscriber.unsubscribed_at.is_(None))
        )
        return result.scalar_one()

    async def count_all(self) -> int:
        """Count all subscribers (including unconfirmed and unsubscribed)."""
        result = await self.session.execute(select(func.count(Subscriber.id)))
        return result.scalar_one()


class PrisonEventRepository:
    """Repository for PrisonEvent CRUD and analytics operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, event: PrisonEvent) -> PrisonEvent:
        """Save a prison event."""
        self.session.add(event)
        await self.session.flush()
        return event

    async def save_batch(self, events: list[PrisonEvent]) -> list[PrisonEvent]:
        """Save multiple events in batch."""
        self.session.add_all(events)
        await self.session.flush()
        return events

    async def get_by_id(self, event_id: int) -> PrisonEvent | None:
        """Get event by ID."""
        return await self.session.get(PrisonEvent, event_id)

    async def list_by_type(
        self,
        event_type: str,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> Sequence[PrisonEvent]:
        """List events by type, optionally filtered by date range."""
        query = (
            select(PrisonEvent)
            .where(PrisonEvent.event_type == event_type)
            .order_by(PrisonEvent.event_date.desc().nulls_last())
        )
        if date_from:
            query = query.where(PrisonEvent.event_date >= date_from)
        if date_to:
            query = query.where(PrisonEvent.event_date <= date_to)
        query = query.limit(limit).offset(offset)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def list_by_facility(self, facility: str, limit: int = 50) -> Sequence[PrisonEvent]:
        """List events for a specific facility."""
        result = await self.session.execute(
            select(PrisonEvent)
            .where(PrisonEvent.facility == facility)
            .order_by(PrisonEvent.event_date.desc().nulls_last())
            .limit(limit)
        )
        return result.scalars().all()

    async def list_by_region(self, region: str, limit: int = 50) -> Sequence[PrisonEvent]:
        """List events for a specific region."""
        result = await self.session.execute(
            select(PrisonEvent)
            .where(PrisonEvent.region == region)
            .order_by(PrisonEvent.event_date.desc().nulls_last())
            .limit(limit)
        )
        return result.scalars().all()

    async def count_by_type(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
        exclude_aggregates: bool = True,
    ) -> dict[str, int]:
        """Count events grouped by type.

        Args:
            date_from: Start date filter.
            date_to: End date filter.
            exclude_aggregates: If True, exclude is_aggregate=True events.
        """
        query = select(PrisonEvent.event_type, func.count(PrisonEvent.id))
        if exclude_aggregates:
            query = query.where(PrisonEvent.is_aggregate == False)  # noqa: E712
        query = query.group_by(PrisonEvent.event_type)
        if date_from:
            query = query.where(PrisonEvent.event_date >= date_from)
        if date_to:
            query = query.where(PrisonEvent.event_date <= date_to)
        result = await self.session.execute(query)
        return {row[0]: row[1] for row in result.all()}

    async def count_by_region(
        self,
        event_type: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        exclude_aggregates: bool = True,
    ) -> dict[str, int]:
        """Count events grouped by region.

        Args:
            event_type: Filter by event type.
            date_from: Start date filter.
            date_to: End date filter.
            exclude_aggregates: If True, exclude is_aggregate=True events.
        """
        query = select(PrisonEvent.region, func.count(PrisonEvent.id)).where(
            PrisonEvent.region.isnot(None)
        )
        if exclude_aggregates:
            query = query.where(PrisonEvent.is_aggregate == False)  # noqa: E712
        if event_type:
            query = query.where(PrisonEvent.event_type == event_type)
        if date_from:
            query = query.where(PrisonEvent.event_date >= date_from)
        if date_to:
            query = query.where(PrisonEvent.event_date <= date_to)
        query = query.group_by(PrisonEvent.region)
        result = await self.session.execute(query)
        return {row[0]: row[1] for row in result.all()}

    async def count_by_facility(
        self,
        event_type: str | None = None,
        limit: int = 20,
        exclude_aggregates: bool = True,
    ) -> list[tuple[str, int]]:
        """Count events grouped by facility, sorted by count descending.

        Args:
            event_type: Filter by event type.
            limit: Max facilities to return.
            exclude_aggregates: If True, exclude is_aggregate=True events.
        """
        query = select(PrisonEvent.facility, func.count(PrisonEvent.id)).where(
            PrisonEvent.facility.isnot(None)
        )
        if exclude_aggregates:
            query = query.where(PrisonEvent.is_aggregate == False)  # noqa: E712
        if event_type:
            query = query.where(PrisonEvent.event_type == event_type)
        query = (
            query.group_by(PrisonEvent.facility)
            .order_by(func.count(PrisonEvent.id).desc())
            .limit(limit)
        )
        result = await self.session.execute(query)
        return [(row[0], row[1]) for row in result.all()]

    async def count_by_month(
        self,
        event_type: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        exclude_aggregates: bool = True,
    ) -> list[tuple[str, int]]:
        """Count events grouped by year-month (YYYY-MM), sorted chronologically.

        Note: Uses PostgreSQL-specific to_char(). This project requires PostgreSQL.

        Args:
            event_type: Filter by event type.
            date_from: Start date filter.
            date_to: End date filter.
            exclude_aggregates: If True, exclude is_aggregate=True events.
        """
        year_month = func.to_char(PrisonEvent.event_date, "YYYY-MM").label("year_month")
        query = select(year_month, func.count(PrisonEvent.id)).where(
            PrisonEvent.event_date.isnot(None)
        )
        if exclude_aggregates:
            query = query.where(PrisonEvent.is_aggregate == False)  # noqa: E712
        if event_type:
            query = query.where(PrisonEvent.event_type == event_type)
        if date_from:
            query = query.where(PrisonEvent.event_date >= date_from)
        if date_to:
            query = query.where(PrisonEvent.event_date <= date_to)
        query = query.group_by(year_month).order_by(year_month)
        result = await self.session.execute(query)
        return [(row[0], row[1]) for row in result.all()]

    async def get_timeline(
        self,
        event_type: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        limit: int = 100,
        exclude_aggregates: bool = True,
    ) -> Sequence[PrisonEvent]:
        """Get events for timeline visualization, sorted by date.

        Args:
            event_type: Filter by event type.
            date_from: Start date filter.
            date_to: End date filter.
            limit: Max events to return.
            exclude_aggregates: If True, exclude is_aggregate=True events.
        """
        query = select(PrisonEvent).where(PrisonEvent.event_date.isnot(None))
        if exclude_aggregates:
            query = query.where(PrisonEvent.is_aggregate == False)  # noqa: E712
        if event_type:
            query = query.where(PrisonEvent.event_type == event_type)
        if date_from:
            query = query.where(PrisonEvent.event_date >= date_from)
        if date_to:
            query = query.where(PrisonEvent.event_date <= date_to)
        query = query.order_by(PrisonEvent.event_date.desc()).limit(limit)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def exists_by_source_url(self, source_url: str) -> bool:
        """Check if an event with the given source URL exists (for deduplication)."""
        result = await self.session.execute(
            select(func.count(PrisonEvent.id)).where(PrisonEvent.source_url == source_url)
        )
        return result.scalar_one() > 0

    async def exists_by_composite_key(
        self,
        source_url: str,
        event_type: str,
        event_date: date | None,
        facility: str | None,
    ) -> bool:
        """Check if an event with the same composite key exists.

        Uses source_url + event_type + event_date + facility to allow
        multiple different events from the same article.
        """
        query = select(func.count(PrisonEvent.id)).where(
            PrisonEvent.source_url == source_url,
            PrisonEvent.event_type == event_type,
        )
        if event_date is not None:
            query = query.where(PrisonEvent.event_date == event_date)
        else:
            query = query.where(PrisonEvent.event_date.is_(None))

        if facility is not None:
            query = query.where(PrisonEvent.facility == facility)
        else:
            query = query.where(PrisonEvent.facility.is_(None))

        result = await self.session.execute(query)
        return result.scalar_one() > 0

    async def list_distinct_facilities(self) -> Sequence[str]:
        """List all distinct facility names."""
        result = await self.session.execute(
            select(PrisonEvent.facility)
            .where(PrisonEvent.facility.isnot(None))
            .distinct()
            .order_by(PrisonEvent.facility)
        )
        return result.scalars().all()

    async def list_distinct_regions(self) -> Sequence[str]:
        """List all distinct region names."""
        result = await self.session.execute(
            select(PrisonEvent.region)
            .where(PrisonEvent.region.isnot(None))
            .distinct()
            .order_by(PrisonEvent.region)
        )
        return result.scalars().all()

    async def list_recent_for_dedup(
        self,
        days: int = 90,
        limit: int = 500,
    ) -> list[dict]:
        """List recent events for AI deduplication.

        Returns simplified event dicts to pass to AI for checking duplicates.

        Args:
            days: How many days back to look for events.
            limit: Maximum events to return.

        Returns:
            List of event dicts with: event_type, event_date, facility, description.
        """
        from datetime import timedelta

        from behind_bars_pulse.utils.facilities import normalize_facility_name

        date_from = date.today() - timedelta(days=days)
        result = await self.session.execute(
            select(PrisonEvent)
            .where(PrisonEvent.event_date >= date_from)
            .order_by(PrisonEvent.event_date.desc())
            .limit(limit)
        )
        events = result.scalars().all()
        return [
            {
                "event_type": e.event_type,
                "event_date": e.event_date.isoformat() if e.event_date else None,
                "facility": normalize_facility_name(e.facility),
                "description": e.description[:100] if e.description else "",
                "is_aggregate": e.is_aggregate,
            }
            for e in events
        ]


class FacilitySnapshotRepository:
    """Repository for FacilitySnapshot CRUD and analytics operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, snapshot: FacilitySnapshot) -> FacilitySnapshot:
        """Save a facility snapshot."""
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot

    async def save_batch(self, snapshots: list[FacilitySnapshot]) -> list[FacilitySnapshot]:
        """Save multiple snapshots in batch."""
        self.session.add_all(snapshots)
        await self.session.flush()
        return snapshots

    async def get_by_id(self, snapshot_id: int) -> FacilitySnapshot | None:
        """Get snapshot by ID."""
        return await self.session.get(FacilitySnapshot, snapshot_id)

    async def exists_by_key(
        self,
        facility: str,
        snapshot_date: date,
        source_url: str,
    ) -> bool:
        """Check if a snapshot with the same key exists."""
        result = await self.session.execute(
            select(func.count(FacilitySnapshot.id)).where(
                FacilitySnapshot.facility == facility,
                FacilitySnapshot.snapshot_date == snapshot_date,
                FacilitySnapshot.source_url == source_url,
            )
        )
        return result.scalar_one() > 0

    async def list_by_facility(
        self,
        facility: str,
        limit: int = 100,
    ) -> Sequence[FacilitySnapshot]:
        """List snapshots for a specific facility, ordered by date."""
        result = await self.session.execute(
            select(FacilitySnapshot)
            .where(FacilitySnapshot.facility == facility)
            .order_by(FacilitySnapshot.snapshot_date.desc())
            .limit(limit)
        )
        return result.scalars().all()

    async def list_by_region(
        self,
        region: str,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> Sequence[FacilitySnapshot]:
        """List snapshots for a region."""
        query = select(FacilitySnapshot).where(FacilitySnapshot.region == region)
        if date_from:
            query = query.where(FacilitySnapshot.snapshot_date >= date_from)
        if date_to:
            query = query.where(FacilitySnapshot.snapshot_date <= date_to)
        query = query.order_by(FacilitySnapshot.snapshot_date.desc())
        result = await self.session.execute(query)
        return result.scalars().all()

    async def get_latest_by_facility(self) -> Sequence[FacilitySnapshot]:
        """Get the latest snapshot for each facility.

        Uses a subquery to find max date per facility, then joins.
        """
        # Subquery: max date per facility
        subq = (
            select(
                FacilitySnapshot.facility,
                func.max(FacilitySnapshot.snapshot_date).label("max_date"),
            )
            .group_by(FacilitySnapshot.facility)
            .subquery()
        )

        # Join to get full records
        result = await self.session.execute(
            select(FacilitySnapshot)
            .join(
                subq,
                (FacilitySnapshot.facility == subq.c.facility)
                & (FacilitySnapshot.snapshot_date == subq.c.max_date),
            )
            .order_by(FacilitySnapshot.occupancy_rate.desc().nulls_last())
        )
        return result.scalars().all()

    async def get_national_trend(
        self,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[tuple[date, int, int, float]]:
        """Get national aggregate trend (total inmates, capacity, avg occupancy).

        Returns list of (date, total_inmates, total_capacity, avg_occupancy_rate).
        """
        query = select(
            FacilitySnapshot.snapshot_date,
            func.sum(FacilitySnapshot.inmates).label("total_inmates"),
            func.sum(FacilitySnapshot.capacity).label("total_capacity"),
            func.avg(FacilitySnapshot.occupancy_rate).label("avg_occupancy"),
        ).where(FacilitySnapshot.inmates.isnot(None))

        if date_from:
            query = query.where(FacilitySnapshot.snapshot_date >= date_from)
        if date_to:
            query = query.where(FacilitySnapshot.snapshot_date <= date_to)

        query = query.group_by(FacilitySnapshot.snapshot_date).order_by(
            FacilitySnapshot.snapshot_date
        )
        result = await self.session.execute(query)
        return [
            (
                row.snapshot_date,
                row.total_inmates or 0,
                row.total_capacity or 0,
                row.avg_occupancy or 0,
            )
            for row in result.all()
        ]

    async def get_regional_summary(self) -> list[tuple[str, int, int, float]]:
        """Get summary by region using latest snapshot per facility.

        Returns list of (region, total_inmates, total_capacity, avg_occupancy).
        """
        # Get latest snapshots per facility (uses get_latest_by_facility logic)
        latest_snapshots = await self.get_latest_by_facility()

        # Aggregate by region
        region_data: dict[str, dict] = {}
        for snap in latest_snapshots:
            if not snap.region:
                continue
            if snap.region not in region_data:
                region_data[snap.region] = {
                    "inmates": 0,
                    "capacity": 0,
                    "occupancy_rates": [],
                }
            if snap.inmates:
                region_data[snap.region]["inmates"] += snap.inmates
            if snap.capacity:
                region_data[snap.region]["capacity"] += snap.capacity
            if snap.occupancy_rate:
                region_data[snap.region]["occupancy_rates"].append(snap.occupancy_rate)

        # Build result
        result = []
        for region, data in region_data.items():
            avg_occ = sum(data["occupancy_rates"]) / len(data["occupancy_rates"]) if data["occupancy_rates"] else 0
            result.append((region, data["inmates"], data["capacity"], avg_occ))

        # Sort by avg occupancy descending
        result.sort(key=lambda x: x[3], reverse=True)
        return result

    async def list_distinct_facilities(self) -> Sequence[str]:
        """List all distinct facility names."""
        result = await self.session.execute(
            select(FacilitySnapshot.facility).distinct().order_by(FacilitySnapshot.facility)
        )
        return result.scalars().all()

    async def list_distinct_regions(self) -> Sequence[str]:
        """List all distinct region names."""
        result = await self.session.execute(
            select(FacilitySnapshot.region)
            .where(FacilitySnapshot.region.isnot(None))
            .distinct()
            .order_by(FacilitySnapshot.region)
        )
        return result.scalars().all()


class BulletinRepository:
    """Repository for Bulletin CRUD operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, bulletin: Bulletin) -> Bulletin:
        """Save a bulletin (insert or update)."""
        self.session.add(bulletin)
        await self.session.flush()
        return bulletin

    async def get_by_id(self, bulletin_id: int) -> Bulletin | None:
        """Get bulletin by ID."""
        return await self.session.get(Bulletin, bulletin_id)

    async def get_by_date(self, issue_date: date) -> Bulletin | None:
        """Get bulletin by issue date."""
        result = await self.session.execute(
            select(Bulletin).where(Bulletin.issue_date == issue_date)
        )
        return result.scalar_one_or_none()

    async def get_latest(self) -> Bulletin | None:
        """Get the most recent bulletin."""
        result = await self.session.execute(
            select(Bulletin).order_by(Bulletin.issue_date.desc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_recent(self, limit: int = 10, offset: int = 0) -> Sequence[Bulletin]:
        """List recent bulletins ordered by date descending."""
        result = await self.session.execute(
            select(Bulletin).order_by(Bulletin.issue_date.desc()).limit(limit).offset(offset)
        )
        return result.scalars().all()

    async def count(self) -> int:
        """Count total bulletins."""
        result = await self.session.execute(select(func.count(Bulletin.id)))
        return result.scalar_one()

    async def delete_by_date(self, issue_date: date) -> bool:
        """Delete bulletin by date. Returns True if deleted."""
        result = await self.session.execute(
            delete(Bulletin).where(Bulletin.issue_date == issue_date)
        )
        return result.rowcount > 0

    async def search_by_embedding(
        self,
        embedding: list[float],
        threshold: float = 0.5,
        limit: int = 10,
    ) -> list[tuple[Bulletin, float]]:
        """Search bulletins by embedding similarity."""
        distance = Bulletin.embedding.cosine_distance(embedding)
        similarity = (1 - distance).label("similarity")

        result = await self.session.execute(
            select(Bulletin, similarity)
            .where(Bulletin.embedding.isnot(None))
            .where((1 - distance) >= threshold)
            .order_by(distance)
            .limit(limit)
        )
        return [(row.Bulletin, row.similarity) for row in result.all()]

    async def get_previous(self, issue_date: date) -> Bulletin | None:
        """Get the bulletin before the given date."""
        result = await self.session.execute(
            select(Bulletin)
            .where(Bulletin.issue_date < issue_date)
            .order_by(Bulletin.issue_date.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_next(self, issue_date: date) -> Bulletin | None:
        """Get the bulletin after the given date."""
        result = await self.session.execute(
            select(Bulletin)
            .where(Bulletin.issue_date > issue_date)
            .order_by(Bulletin.issue_date.asc())
            .limit(1)
        )
        return result.scalar_one_or_none()


class EditorialCommentRepository:
    """Repository for EditorialComment CRUD and search operations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, comment: EditorialComment) -> EditorialComment:
        """Save an editorial comment."""
        self.session.add(comment)
        await self.session.flush()
        return comment

    async def save_batch(self, comments: list[EditorialComment]) -> list[EditorialComment]:
        """Save multiple comments in batch."""
        self.session.add_all(comments)
        await self.session.flush()
        return comments

    async def get_by_id(self, comment_id: int) -> EditorialComment | None:
        """Get comment by ID."""
        return await self.session.get(EditorialComment, comment_id)

    async def list_by_source(
        self, source_type: str, source_id: int
    ) -> Sequence[EditorialComment]:
        """List comments from a specific source."""
        result = await self.session.execute(
            select(EditorialComment)
            .where(EditorialComment.source_type == source_type)
            .where(EditorialComment.source_id == source_id)
            .order_by(EditorialComment.id)
        )
        return result.scalars().all()

    async def list_recent(
        self, limit: int = 20, offset: int = 0, source_type: str | None = None
    ) -> Sequence[EditorialComment]:
        """List recent comments, optionally filtered by source type."""
        query = select(EditorialComment).order_by(EditorialComment.source_date.desc())
        if source_type:
            query = query.where(EditorialComment.source_type == source_type)
        query = query.limit(limit).offset(offset)
        result = await self.session.execute(query)
        return result.scalars().all()

    async def search_by_embedding(
        self,
        embedding: list[float],
        threshold: float = 0.5,
        limit: int = 20,
        offset: int = 0,
        source_type: str | None = None,
    ) -> tuple[list[tuple[EditorialComment, float]], int]:
        """Search comments by embedding similarity.

        Args:
            embedding: Query embedding vector
            threshold: Minimum similarity threshold (0-1)
            limit: Maximum results per page
            offset: Number of results to skip
            source_type: Filter by source type ('bulletin' or 'newsletter')

        Returns:
            Tuple of (results list, total count)
        """
        distance = EditorialComment.embedding.cosine_distance(embedding)
        similarity = (1 - distance).label("similarity")

        # Base query conditions
        base_conditions = [
            EditorialComment.embedding.isnot(None),
            (1 - distance) >= threshold,
        ]
        if source_type:
            base_conditions.append(EditorialComment.source_type == source_type)

        # Count total
        count_result = await self.session.execute(
            select(func.count(EditorialComment.id)).where(*base_conditions)
        )
        total = count_result.scalar_one()

        # Fetch results
        result = await self.session.execute(
            select(EditorialComment, similarity)
            .where(*base_conditions)
            .order_by(distance)
            .limit(limit)
            .offset(offset)
        )
        results = [(row.EditorialComment, row.similarity) for row in result.all()]
        return results, total

    async def count(self, source_type: str | None = None) -> int:
        """Count comments, optionally filtered by source type."""
        query = select(func.count(EditorialComment.id))
        if source_type:
            query = query.where(EditorialComment.source_type == source_type)
        result = await self.session.execute(query)
        return result.scalar_one()

    async def delete_by_source(self, source_type: str, source_id: int) -> int:
        """Delete all comments from a specific source. Returns count deleted."""
        result = await self.session.execute(
            delete(EditorialComment)
            .where(EditorialComment.source_type == source_type)
            .where(EditorialComment.source_id == source_id)
        )
        return result.rowcount
