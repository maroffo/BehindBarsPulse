# ABOUTME: Newsletter generation orchestrator.
# ABOUTME: Coordinates feed fetching, AI processing, and content assembly.

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
        use_collected: bool = False,
        collection_date: date | None = None,
    ) -> tuple[NewsletterContent, list[PressReviewCategory], dict[str, EnrichedArticle]]:
        """Run the full newsletter generation pipeline.

        Args:
            use_collected: If True, use pre-collected articles from storage.
            collection_date: Date to load articles from. Defaults to today.

        Returns:
            Tuple of (NewsletterContent, press review categories, enriched articles).
        """
        log.info("starting_newsletter_generation")

        # Get enriched articles
        if use_collected:
            collection_date = collection_date or date.today()
            enriched_articles = self.narrative_storage.load_collected_articles(collection_date)
            if not enriched_articles:
                log.warning("no_collected_articles_falling_back_to_fetch")
                enriched_articles = self._fetch_and_enrich()
        else:
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
        )
        log.info("newsletter_content_generated")

        # Review and polish content
        newsletter_content = self.ai_service.review_newsletter_content(
            newsletter_content,
            previous_issues,
        )
        log.info("newsletter_content_reviewed")

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
        """
        for category in press_review:
            for article in category.articles:
                url = str(article.link)
                if url in enriched_articles:
                    enriched = enriched_articles[url]
                    article.author = enriched.author
                    article.source = enriched.source
                    article.summary = enriched.summary

        return press_review

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
