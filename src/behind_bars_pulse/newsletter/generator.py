# ABOUTME: Newsletter generation orchestrator.
# ABOUTME: Coordinates feed fetching, AI processing, and content assembly.

import asyncio
from datetime import date
from pathlib import Path

import structlog

from behind_bars_pulse.ai.service import AIService
from behind_bars_pulse.config import Settings, get_settings
from behind_bars_pulse.feeds.fetcher import FeedFetcher
from behind_bars_pulse.models import (
    EnrichedArticle,
    NewsletterContent,
    NewsletterContext,
    PressReviewCategory,
)
from behind_bars_pulse.narrative.models import NarrativeContext as NarrativeMemory
from behind_bars_pulse.narrative.storage import NarrativeStorage

log = structlog.get_logger()


def _load_articles_from_db(
    end_date: date, days_back: int = 7
) -> dict[str, EnrichedArticle] | None:
    """Load articles from database for a date range.

    Args:
        end_date: The end date of the range (typically today or newsletter date).
        days_back: Number of days to look back (default 7 for weekly newsletter).

    Returns None if DB is not configured or no articles found.
    """
    from datetime import timedelta

    try:
        from behind_bars_pulse.db.repository import ArticleRepository
        from behind_bars_pulse.db.session import get_session

        start_date = end_date - timedelta(days=days_back - 1)

        async def _fetch():
            async with get_session() as session:
                repo = ArticleRepository(session)
                articles = await repo.list_by_date_range(start_date, end_date)
                return articles

        # Run async code synchronously
        articles = asyncio.run(_fetch())

        if not articles:
            return None

        # Convert DB models to EnrichedArticle
        enriched: dict[str, EnrichedArticle] = {}
        for article in articles:
            enriched[article.link] = EnrichedArticle(
                title=article.title,
                link=article.link,
                content=article.content,
                author=article.author,
                source=article.source,
                summary=article.summary,
            )

        return enriched

    except Exception as e:
        log.debug("db_load_skipped", error=str(e), hint="DB not configured or unavailable")
        return None


class NewsletterGenerator:
    """Orchestrates the newsletter generation pipeline."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.feed_fetcher = FeedFetcher(self.settings)
        self.ai_service = AIService(self.settings)
        self.narrative_storage = NarrativeStorage(self.settings)

    def close(self) -> None:
        """Close resources."""
        self.feed_fetcher.close()

    def __enter__(self) -> "NewsletterGenerator":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def read_previous_issues(self) -> list[str]:
        """Read previous newsletter issues for context.

        Returns:
            List of previous newsletter texts.
        """
        issues: list[str] = []
        issues_dir = Path(self.settings.previous_issues_dir)

        if not issues_dir.exists():
            log.warning("previous_issues_dir_missing", path=str(issues_dir))
            return issues

        for file_path in sorted(issues_dir.glob("*.txt")):
            log.debug("reading_previous_issue", file=file_path.name)
            issues.append(file_path.read_text(encoding="utf-8"))

        log.info("loaded_previous_issues", count=len(issues))
        return issues

    def load_narrative_context(self) -> NarrativeMemory | None:
        """Load narrative context if available.

        Returns:
            NarrativeMemory if available, None if empty or missing.
        """
        try:
            context = self.narrative_storage.load_context()
            if context.ongoing_storylines or context.key_characters:
                log.info(
                    "narrative_context_loaded",
                    stories=len(context.ongoing_storylines),
                    characters=len(context.key_characters),
                )
                return context
            log.info("narrative_context_empty")
            return None
        except Exception:
            log.exception("narrative_context_load_failed")
            return None

    def generate(
        self,
        collection_date: date | None = None,
        force_fetch: bool = False,
        use_db: bool = True,
        days_back: int = 7,
        first_issue: bool = False,
        update_narrative: bool = True,
    ) -> tuple[NewsletterContent, list[PressReviewCategory], dict[str, EnrichedArticle]]:
        """Run the full newsletter generation pipeline.

        Article loading priority:
        1. Database (if use_db=True and DB configured)
        2. Pre-collected JSON files
        3. Fresh fetch from RSS

        Args:
            collection_date: End date for article collection. Defaults to today.
            force_fetch: If True, skip collected articles and fetch fresh.
            use_db: If True, try loading from database first.
            days_back: Number of days to look back for articles (default 7 for weekly).
            first_issue: If True, include introductory text for first newsletter.
            update_narrative: If True, update narrative context after generation.

        Returns:
            Tuple of (NewsletterContent, press review categories, enriched articles).
        """
        log.info("starting_newsletter_generation", days_back=days_back)
        collection_date = collection_date or date.today()

        enriched_articles: dict[str, EnrichedArticle] = {}

        # 1. Try database first (if enabled)
        if not force_fetch and use_db:
            enriched_articles = _load_articles_from_db(collection_date, days_back) or {}
            if enriched_articles:
                log.info(
                    "using_db_articles",
                    count=len(enriched_articles),
                    end_date=str(collection_date),
                    days_back=days_back,
                )

        # 2. Fall back to pre-collected JSON files
        if not enriched_articles and not force_fetch:
            enriched_articles = self.narrative_storage.load_collected_articles(collection_date)
            if enriched_articles:
                log.info(
                    "using_collected_articles",
                    count=len(enriched_articles),
                    date=str(collection_date),
                )

        # 3. Fall back to fetching fresh from RSS
        if not enriched_articles:
            log.info("fetching_fresh_articles")
            enriched_articles = self._fetch_and_enrich()

        if not enriched_articles:
            raise ValueError("No articles available for newsletter")

        # Load context sources
        previous_issues = self.read_previous_issues()
        narrative_context = self.load_narrative_context()

        # Check for due follow-ups
        due_followups = []
        if narrative_context:
            due_followups = narrative_context.get_due_followups(date.today())
            if due_followups:
                log.info("due_followups_found", count=len(due_followups))

        # Generate newsletter content with narrative context
        newsletter_content = self.ai_service.generate_newsletter_content(
            enriched_articles,
            previous_issues,
            narrative_context=narrative_context,
            first_issue=first_issue,
        )
        log.info("newsletter_content_generated", first_issue=first_issue)

        # Review and polish content (optional - continue with unreviewed if fails)
        try:
            newsletter_content = self.ai_service.review_newsletter_content(
                newsletter_content,
                previous_issues,
            )
            log.info("newsletter_content_reviewed")
        except (ValueError, Exception) as e:
            log.warning(
                "review_step_skipped",
                error=str(e),
                hint="Using unreviewed content - newsletter will still be generated",
            )

        # Generate press review with categorization
        # Convert EnrichedArticle to Article for press review
        from behind_bars_pulse.models import Article

        articles_for_review = {
            url: Article(title=a.title, link=a.link, content=a.content)
            for url, a in enriched_articles.items()
        }
        press_review = self.ai_service.generate_press_review(articles_for_review)
        log.info("press_review_generated", category_count=len(press_review))

        # Merge enriched data into press review articles
        press_review = self._merge_enriched_data(press_review, enriched_articles)

        # Update narrative context with extracted stories and entities
        if update_narrative:
            self._update_narrative_context(enriched_articles, narrative_context)

        return newsletter_content, press_review, enriched_articles

    def _fetch_and_enrich(self) -> dict[str, EnrichedArticle]:
        """Fetch articles from RSS and enrich with AI metadata."""
        articles = self.feed_fetcher.fetch_feed()
        log.info("articles_fetched", count=len(articles))

        if not articles:
            return {}

        enriched_articles = self.ai_service.enrich_articles(articles)
        log.info("articles_enriched", count=len(enriched_articles))

        return enriched_articles

    def _merge_enriched_data(
        self,
        press_review: list[PressReviewCategory],
        enriched_articles: dict[str, EnrichedArticle],
    ) -> list[PressReviewCategory]:
        """Merge enriched article data into press review structure.

        The press review from AI only has title/link/importance.
        This adds author/source/summary from enriched articles.

        Matches by title (normalized) since LLM sometimes hallucinates URLs.
        """
        # Build title-to-enriched lookup (normalized titles)
        title_lookup: dict[str, tuple[str, EnrichedArticle]] = {}
        for url, enriched in enriched_articles.items():
            normalized_title = enriched.title.lower().strip()
            title_lookup[normalized_title] = (url, enriched)

        matched = 0
        unmatched = 0

        for category in press_review:
            for article in category.articles:
                normalized_title = article.title.lower().strip()
                if normalized_title in title_lookup:
                    url, enriched = title_lookup[normalized_title]
                    article.author = enriched.author
                    article.source = enriched.source
                    article.summary = enriched.summary
                    # Fix URL if AI hallucinated it
                    article.link = enriched.link
                    matched += 1
                else:
                    log.warning(
                        "article_merge_failed",
                        title=article.title[:50],
                        hint="Article not found in enriched data",
                    )
                    unmatched += 1

        log.debug("merge_complete", matched=matched, unmatched=unmatched)
        return press_review

    def _update_narrative_context(
        self,
        enriched_articles: dict[str, EnrichedArticle],
        existing_context: NarrativeMemory | None,
    ) -> None:
        """Extract stories and entities from articles and update narrative context.

        Args:
            enriched_articles: Articles to extract from.
            existing_context: Current narrative context (may be None).
        """
        import uuid

        from behind_bars_pulse.narrative.models import (
            CharacterPosition,
            FollowUp,
            KeyCharacter,
            StoryThread,
        )

        log.info("updating_narrative_context", article_count=len(enriched_articles))

        # Load or create context
        context = existing_context or NarrativeMemory()

        # Extract stories
        try:
            existing_stories = [s.model_dump(mode="json") for s in context.ongoing_storylines]
            story_updates = self.ai_service.extract_stories(enriched_articles, existing_stories)

            # Update existing stories
            for update in story_updates.get("updated_stories", []):
                for story in context.ongoing_storylines:
                    if story.id == update.get("id"):
                        story.summary = update.get("new_summary", story.summary)
                        story.keywords = update.get("new_keywords", story.keywords)
                        story.impact_score = update.get("impact_score", story.impact_score)
                        story.last_update = date.today()
                        story.mention_count += 1
                        for url in update.get("article_urls", []):
                            if url not in [str(u) for u in story.related_articles]:
                                story.related_articles.append(url)
                        log.debug("story_updated", story_id=story.id, topic=story.topic)

            # Add new stories
            for new_story in story_updates.get("new_stories", []):
                story = StoryThread(
                    id=str(uuid.uuid4()),
                    topic=new_story.get("topic", "Unknown"),
                    summary=new_story.get("summary", ""),
                    keywords=new_story.get("keywords", []),
                    impact_score=new_story.get("impact_score", 0.5),
                    first_seen=date.today(),
                    last_update=date.today(),
                    related_articles=new_story.get("article_urls", []),
                )
                context.ongoing_storylines.append(story)
                log.info("new_story_added", topic=story.topic)

        except Exception as e:
            log.warning("story_extraction_failed", error=str(e))

        # Extract entities (characters)
        try:
            existing_chars = [c.model_dump(mode="json") for c in context.key_characters]
            entity_updates = self.ai_service.extract_entities(enriched_articles, existing_chars)

            # Update existing characters
            for update in entity_updates.get("updated_characters", []):
                for char in context.key_characters:
                    if char.name.lower() == update.get("name", "").lower():
                        new_pos = update.get("new_position", {})
                        if new_pos:
                            char.positions.append(
                                CharacterPosition(
                                    date=date.today(),
                                    stance=new_pos.get("stance", ""),
                                    source_url=new_pos.get("source_url"),
                                )
                            )
                        log.debug("character_updated", name=char.name)

            # Add new characters
            for new_char in entity_updates.get("new_characters", []):
                initial_pos = new_char.get("initial_position", {})
                char = KeyCharacter(
                    name=new_char.get("name", "Unknown"),
                    role=new_char.get("role", ""),
                    aliases=new_char.get("aliases", []),
                    positions=[
                        CharacterPosition(
                            date=date.today(),
                            stance=initial_pos.get("stance", ""),
                            source_url=initial_pos.get("source_url"),
                        )
                    ]
                    if initial_pos
                    else [],
                )
                context.key_characters.append(char)
                log.info("new_character_added", name=char.name)

        except Exception as e:
            log.warning("entity_extraction_failed", error=str(e))

        # Extract follow-ups
        try:
            story_ids = [s.id for s in context.ongoing_storylines]
            followup_data = self.ai_service.detect_followups(enriched_articles, story_ids)

            for fu in followup_data.get("followups", []):
                followup = FollowUp(
                    id=str(uuid.uuid4()),
                    event=fu.get("event", ""),
                    expected_date=date.fromisoformat(fu.get("expected_date", str(date.today()))),
                    story_id=fu.get("story_id"),
                    created_at=date.today(),
                )
                context.pending_followups.append(followup)
                log.info("followup_added", followup_event=followup.event[:50])

        except Exception as e:
            log.warning("followup_extraction_failed", error=str(e))

        # Archive old stories
        archived = self.narrative_storage.archive_old_stories(context)
        if archived:
            log.info("stories_archived", count=archived)

        # Save updated context
        self.narrative_storage.save_context(context)
        log.info(
            "narrative_context_updated",
            stories=len(context.ongoing_storylines),
            characters=len(context.key_characters),
            followups=len(context.pending_followups),
        )

    def build_context(
        self,
        newsletter_content: NewsletterContent,
        press_review: list[PressReviewCategory],
        today_str: str,
    ) -> NewsletterContext:
        """Build the complete context for email rendering.

        Args:
            newsletter_content: Generated newsletter content.
            press_review: Categorized press review.
            today_str: Formatted date string.

        Returns:
            Complete NewsletterContext for template rendering.
        """
        subject = (
            f"⚖️⛓️BehindBars - Notizie dal mondo della giustizia e delle carceri italiane - "
            f"{today_str}"
        )

        return NewsletterContext(
            subject=subject,
            today_str=today_str,
            newsletter_title=newsletter_content.title,
            newsletter_subtitle=newsletter_content.subtitle,
            newsletter_opening=newsletter_content.opening,
            newsletter_closing=newsletter_content.closing,
            press_review=press_review,
        )
