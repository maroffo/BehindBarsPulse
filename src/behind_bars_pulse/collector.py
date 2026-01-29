# ABOUTME: Daily article collector for narrative-aware newsletter pipeline.
# ABOUTME: Fetches, enriches articles and updates narrative context.

import uuid
from datetime import date

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

log = structlog.get_logger()


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
