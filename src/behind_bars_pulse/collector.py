# ABOUTME: Daily article collector for narrative-aware newsletter pipeline.
# ABOUTME: Fetches, enriches articles, updates narrative context, and extracts prison events.

import asyncio
import uuid
from datetime import date, datetime
from typing import Any

import structlog

from behind_bars_pulse.ai.service import AIService
from behind_bars_pulse.config import Settings, get_settings
from behind_bars_pulse.feeds.fetcher import FeedFetcher
from behind_bars_pulse.models import EnrichedArticle
from behind_bars_pulse.narrative.models import (
    CharacterPosition,
    FollowUp,
    KeyCharacter,
    NarrativeContext,
    StoryThread,
)
from behind_bars_pulse.narrative.storage import NarrativeStorage
from behind_bars_pulse.utils.facilities import get_facility_region, normalize_facility_name

log = structlog.get_logger()


def _save_prison_events_to_db(events: list[dict], article_url_to_id: dict[str, int]) -> int:
    """Save extracted prison events to database.

    Args:
        events: List of event dicts from AI extraction.
        article_url_to_id: Mapping of article URLs to DB article IDs.

    Returns:
        Number of events saved. Returns 0 if DB is not available.
    """
    try:
        from behind_bars_pulse.db.models import PrisonEvent
        from behind_bars_pulse.db.repository import PrisonEventRepository
        from behind_bars_pulse.db.session import get_session

        async def _save():
            saved_count = 0
            skipped_count = 0

            async with get_session() as session:
                repo = PrisonEventRepository(session)

                for event_data in events:
                    source_url = event_data.get("source_url", "")
                    event_type = event_data.get("event_type", "unknown")

                    # Normalize facility name for consistency
                    raw_facility = event_data.get("facility")
                    facility = normalize_facility_name(raw_facility)

                    # Infer region from facility if not provided
                    region = event_data.get("region")
                    if not region and facility:
                        region = get_facility_region(facility)

                    # Parse event date
                    event_date = None
                    if event_data.get("event_date"):
                        try:
                            event_date = date.fromisoformat(event_data["event_date"])
                        except ValueError:
                            log.warning(
                                "invalid_event_date",
                                date=event_data["event_date"],
                            )

                    # Check for duplicate by composite key (url + type + date + normalized facility)
                    # This allows multiple different events from the same article
                    if await repo.exists_by_composite_key(
                        source_url, event_type, event_date, facility
                    ):
                        skipped_count += 1
                        continue

                    # Get article ID if available
                    article_id = article_url_to_id.get(source_url)

                    # Determine if this is an aggregate statistic
                    is_aggregate = event_data.get("is_aggregate", False)

                    event = PrisonEvent(
                        event_type=event_type,
                        event_date=event_date,
                        facility=facility,
                        region=region,
                        count=event_data.get("count"),
                        description=event_data.get("description", ""),
                        source_url=source_url,
                        article_id=article_id,
                        confidence=float(event_data.get("confidence", 1.0)),
                        is_aggregate=is_aggregate,
                        extracted_at=datetime.utcnow(),
                    )
                    await repo.save(event)
                    saved_count += 1

                await session.commit()

            log.info("prison_events_saved", saved=saved_count, skipped=skipped_count)
            return saved_count

        return asyncio.run(_save())

    except Exception as e:
        log.debug("prison_events_save_skipped", error=str(e))
        return 0


def _get_existing_events_for_dedup() -> list[dict[str, Any]]:
    """Get recent events from DB for AI deduplication.

    Returns:
        List of event dicts, or empty list if DB not available.
    """
    try:
        from behind_bars_pulse.db.repository import PrisonEventRepository
        from behind_bars_pulse.db.session import get_session

        async def _fetch():
            async with get_session() as session:
                repo = PrisonEventRepository(session)
                return await repo.list_recent_for_dedup(days=90)

        return asyncio.run(_fetch())

    except Exception as e:
        log.debug("existing_events_fetch_skipped", error=str(e))
        return []


def _save_articles_to_db(
    articles: dict[str, EnrichedArticle], collection_date: date
) -> tuple[int, dict[str, int]]:
    """Save enriched articles to database with embeddings.

    Args:
        articles: Dictionary of URL -> EnrichedArticle.
        collection_date: Date to use as published_date.

    Returns:
        Tuple of (articles saved count, URL-to-article-ID mapping).
    """
    try:
        from behind_bars_pulse.db.models import Article as DbArticle
        from behind_bars_pulse.db.session import get_session
        from behind_bars_pulse.services.newsletter_service import NewsletterService

        async def _save():
            svc = NewsletterService()
            saved_count = 0
            skipped_count = 0
            url_to_id: dict[str, int] = {}

            async with get_session() as session:
                for url, article in articles.items():
                    # Check if article already exists
                    from sqlalchemy import select

                    existing = await session.execute(select(DbArticle).where(DbArticle.link == url))
                    existing_article = existing.scalar_one_or_none()
                    if existing_article:
                        skipped_count += 1
                        url_to_id[url] = existing_article.id
                        continue

                    # Generate embedding
                    text = article.title
                    if article.summary:
                        text = f"{article.title}. {article.summary}"

                    try:
                        embedding = await svc.generate_embedding(text)
                    except Exception as e:
                        log.warning("embedding_generation_failed", url=url[:50], error=str(e))
                        embedding = None

                    # Create DB article
                    db_article = DbArticle(
                        title=article.title,
                        link=url,
                        content=article.content,
                        author=article.author or None,
                        source=article.source or None,
                        summary=article.summary or None,
                        published_date=collection_date,
                        embedding=embedding,
                    )
                    session.add(db_article)
                    await session.flush()  # Get the ID
                    url_to_id[url] = db_article.id
                    saved_count += 1

                await session.commit()

            log.info("db_save_complete", saved=saved_count, skipped=skipped_count)
            return saved_count, url_to_id

        return asyncio.run(_save())

    except Exception as e:
        log.debug("db_save_skipped", error=str(e), hint="DB not configured or unavailable")
        return 0, {}


class ArticleCollector:
    """Collects and enriches articles, updating narrative context."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.feed_fetcher = FeedFetcher(self.settings)
        self.ai_service = AIService(self.settings)
        self.storage = NarrativeStorage(self.settings)

    def close(self) -> None:
        """Close resources."""
        self.feed_fetcher.close()

    def __enter__(self) -> "ArticleCollector":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def collect(
        self,
        collection_date: date | None = None,
        update_narrative: bool = True,
    ) -> dict[str, EnrichedArticle]:
        """Run daily collection pipeline.

        1. Fetch articles from RSS
        2. Enrich with AI metadata
        3. Update narrative context (stories, characters, follow-ups)
        4. Save collected articles to dated file

        Args:
            collection_date: Date to use for collection. Defaults to today.
            update_narrative: Whether to extract and update narrative context.

        Returns:
            Dictionary of URL -> EnrichedArticle.
        """
        collection_date = collection_date or date.today()
        log.info("starting_collection", date=collection_date.isoformat())

        # Fetch raw articles from RSS
        articles = self.feed_fetcher.fetch_feed()
        log.info("articles_fetched", count=len(articles))

        if not articles:
            log.warning("no_articles_fetched")
            return {}

        # Enrich articles with AI-extracted metadata
        enriched = self.ai_service.enrich_articles(articles)
        log.info("articles_enriched", count=len(enriched))

        # Update narrative context with story/character/followup extraction
        if update_narrative:
            self._update_narrative_context(enriched, collection_date)

        # Save to dated collection file
        self.storage.save_collected_articles(enriched, collection_date)

        # Save to database if configured (with embeddings)
        db_saved, url_to_id = _save_articles_to_db(enriched, collection_date)
        if db_saved > 0:
            log.info("articles_saved_to_db", count=db_saved)

        # Extract and save prison events
        self._extract_and_save_events(enriched, url_to_id)

        log.info("collection_complete", date=collection_date.isoformat(), count=len(enriched))
        return enriched

    def _update_narrative_context(
        self,
        articles: dict[str, EnrichedArticle],
        collection_date: date,
    ) -> NarrativeContext:
        """Extract and update narrative context from articles.

        Args:
            articles: Enriched articles to process.
            collection_date: Date of collection.

        Returns:
            Updated NarrativeContext.
        """
        log.info("updating_narrative_context")

        context = self.storage.load_context()

        # Archive old stories
        archived = self.storage.archive_old_stories(context, collection_date)
        if archived:
            log.info("stories_archived", count=archived)

        # Extract stories
        self._extract_and_update_stories(articles, context, collection_date)

        # Extract entities
        self._extract_and_update_characters(articles, context, collection_date)

        # Detect follow-ups
        self._detect_and_add_followups(articles, context, collection_date)

        # Save updated context
        self.storage.save_context(context)

        return context

    def _extract_and_update_stories(
        self,
        articles: dict[str, EnrichedArticle],
        context: NarrativeContext,
        collection_date: date,
    ) -> None:
        """Extract story threads and update context."""
        existing_stories = [
            {
                "id": s.id,
                "topic": s.topic,
                "summary": s.summary,
                "keywords": s.keywords,
                "status": s.status,
            }
            for s in context.ongoing_storylines
            if s.status != "resolved"
        ]

        try:
            result = self.ai_service.extract_stories(articles, existing_stories)
        except Exception:
            log.exception("story_extraction_failed")
            return

        # Update existing stories
        for update in result.get("updated_stories", []):
            story = context.get_story_by_id(update.get("id", ""))
            if story:
                story.summary = update.get("new_summary", story.summary)
                story.keywords = list(set(story.keywords + update.get("new_keywords", [])))
                story.impact_score = float(update.get("impact_score", story.impact_score))
                story.last_update = collection_date
                story.mention_count += 1
                for url in update.get("article_urls", []):
                    if url not in [str(u) for u in story.related_articles]:
                        story.related_articles.append(url)
                log.info("story_updated", story_id=story.id, topic=story.topic)

        # Add new stories
        for new_story in result.get("new_stories", []):
            story = StoryThread(
                id=str(uuid.uuid4()),
                topic=new_story.get("topic", "Unknown"),
                first_seen=collection_date,
                last_update=collection_date,
                summary=new_story.get("summary", ""),
                keywords=new_story.get("keywords", []),
                impact_score=float(new_story.get("impact_score", 0.5)),
                related_articles=new_story.get("article_urls", []),
            )
            context.ongoing_storylines.append(story)
            log.info("story_created", story_id=story.id, topic=story.topic)

    def _extract_and_update_characters(
        self,
        articles: dict[str, EnrichedArticle],
        context: NarrativeContext,
        collection_date: date,
    ) -> None:
        """Extract character information and update context."""
        existing_characters = [
            {
                "name": c.name,
                "role": c.role,
                "aliases": c.aliases,
            }
            for c in context.key_characters
        ]

        try:
            result = self.ai_service.extract_entities(articles, existing_characters)
        except Exception:
            log.exception("entity_extraction_failed")
            return

        # Update existing characters
        for update in result.get("updated_characters", []):
            char = context.get_character_by_name(update.get("name", ""))
            if char and update.get("new_position"):
                pos_data = update["new_position"]
                char.positions.append(
                    CharacterPosition(
                        date=collection_date,
                        stance=pos_data.get("stance", ""),
                        source_url=pos_data.get("source_url"),
                    )
                )
                log.info("character_updated", name=char.name)

        # Add new characters
        for new_char in result.get("new_characters", []):
            positions = []
            if new_char.get("initial_position"):
                pos_data = new_char["initial_position"]
                positions.append(
                    CharacterPosition(
                        date=collection_date,
                        stance=pos_data.get("stance", ""),
                        source_url=pos_data.get("source_url"),
                    )
                )

            char = KeyCharacter(
                name=new_char.get("name", "Unknown"),
                role=new_char.get("role", ""),
                aliases=new_char.get("aliases", []),
                positions=positions,
            )
            context.key_characters.append(char)
            log.info("character_created", name=char.name)

    def _detect_and_add_followups(
        self,
        articles: dict[str, EnrichedArticle],
        context: NarrativeContext,
        collection_date: date,
    ) -> None:
        """Detect follow-up events and add to context."""
        story_ids = [s.id for s in context.ongoing_storylines if s.status == "active"]

        try:
            result = self.ai_service.detect_followups(articles, story_ids)
        except Exception:
            log.exception("followup_detection_failed")
            return

        for followup_data in result.get("followups", []):
            try:
                expected_date = date.fromisoformat(followup_data.get("expected_date", ""))
            except ValueError:
                log.warning("invalid_followup_date", data=followup_data)
                continue

            followup = FollowUp(
                id=str(uuid.uuid4()),
                event=followup_data.get("event", "Unknown event"),
                expected_date=expected_date,
                story_id=followup_data.get("story_id"),
                created_at=collection_date,
            )
            context.pending_followups.append(followup)
            log.info(
                "followup_created",
                followup_event=followup.event,
                followup_date=str(followup.expected_date),
            )

    def _extract_and_save_events(
        self,
        articles: dict[str, EnrichedArticle],
        url_to_id: dict[str, int],
    ) -> None:
        """Extract prison events from articles and save to database.

        Args:
            articles: Enriched articles to process.
            url_to_id: Mapping of article URLs to database IDs.
        """
        if not articles:
            return

        log.info("extracting_prison_events", article_count=len(articles))

        # Get existing events for AI deduplication
        existing_events = _get_existing_events_for_dedup()
        log.info("existing_events_for_dedup", count=len(existing_events))

        try:
            result = self.ai_service.extract_prison_events(articles, existing_events)
        except Exception:
            log.exception("prison_event_extraction_failed")
            return

        events = result.get("events", [])
        if not events:
            log.info("no_prison_events_extracted")
            return

        log.info("prison_events_extracted", count=len(events))

        # Save to database (with normalized facility names)
        saved = _save_prison_events_to_db(events, url_to_id)
        if saved > 0:
            log.info("prison_events_saved_to_db", count=saved)
