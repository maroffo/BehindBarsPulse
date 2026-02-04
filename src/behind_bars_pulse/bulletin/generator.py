# ABOUTME: Bulletin generator for daily editorial commentary.
# ABOUTME: Orchestrates article loading, AI generation, and DB persistence.

from datetime import date, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from behind_bars_pulse.ai.service import AIService
from behind_bars_pulse.bulletin.models import Bulletin, EditorialCommentChunk
from behind_bars_pulse.config import Settings, get_settings
from behind_bars_pulse.db.models import Article as ArticleORM
from behind_bars_pulse.models import EnrichedArticle

if TYPE_CHECKING:
    from behind_bars_pulse.models import Article

log = structlog.get_logger()


class BulletinGenerator:
    """Generator for daily editorial bulletins on prison news."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.ai_service = AIService(self.settings)

    def generate(self, issue_date: date | None = None) -> Bulletin | None:
        """Generate a bulletin for the given date.

        Args:
            issue_date: Date for the bulletin. Defaults to today.
                        Analyzes articles from the day before.

        Returns:
            Generated Bulletin, or None if no articles found.
        """
        issue_date = issue_date or date.today()
        articles_date = issue_date - timedelta(days=1)

        log.info("generating_bulletin", issue_date=issue_date, articles_date=articles_date)

        # Load articles from the day before
        articles = self._load_articles_from_db(articles_date)

        if not articles:
            log.warning("no_articles_for_bulletin", date=articles_date)
            return None

        # Generate bulletin content via AI
        bulletin_content = self.ai_service.generate_bulletin(
            articles=articles,
            issue_date=issue_date.isoformat(),
        )

        # Generate press review with thematic categories (like newsletter)
        press_review = self.ai_service.generate_press_review(
            articles={url: self._to_article(a) for url, a in articles.items()}
        )
        press_review_data = [cat.model_dump(mode="json") for cat in press_review]

        return Bulletin(
            issue_date=issue_date,
            title=bulletin_content.title,
            subtitle=bulletin_content.subtitle,
            content=bulletin_content.content,
            key_topics=bulletin_content.key_topics,
            sources_cited=bulletin_content.sources_cited,
            articles_count=len(articles),
            press_review=press_review_data,
        )

    def _to_article(self, enriched: EnrichedArticle) -> "Article":
        """Convert EnrichedArticle to Article for press review generation."""
        from behind_bars_pulse.models import Article

        return Article(
            title=enriched.title,
            link=enriched.link,
            content=enriched.content,
            published_date=enriched.published_date,
        )

    def _load_articles_from_db(self, articles_date: date) -> dict[str, EnrichedArticle]:
        """Load articles from database for a specific date.

        Args:
            articles_date: Date to load articles for.

        Returns:
            Dictionary mapping URLs to EnrichedArticle objects.
        """
        if not self.settings.database_url:
            log.warning("no_database_url_configured")
            return {}

        # Use sync connection to avoid event loop issues
        async_url = str(self.settings.database_url)
        sync_url = async_url.replace("+asyncpg", "").replace("postgresql+asyncpg", "postgresql")

        try:
            engine = create_engine(sync_url)
            with Session(engine) as session:
                db_articles = (
                    session.query(ArticleORM)
                    .filter(ArticleORM.published_date == articles_date)
                    .all()
                )

                articles = {}
                for db_article in db_articles:
                    articles[db_article.link] = EnrichedArticle(
                        title=db_article.title,
                        link=db_article.link,
                        content=db_article.content,
                        author=db_article.author or "",
                        source=db_article.source or "",
                        summary=db_article.summary or "",
                        published_date=db_article.published_date,
                    )

                log.info("loaded_articles_from_db", count=len(articles), date=articles_date)
                return articles

        except Exception as e:
            log.error("db_load_failed", error=str(e))
            return {}

    def extract_editorial_comments(
        self,
        bulletin: Bulletin,
        bulletin_id: int,
    ) -> list[EditorialCommentChunk]:
        """Extract searchable comment chunks from a bulletin.

        Splits the bulletin content into logical chunks for semantic search.

        Args:
            bulletin: The bulletin to extract from.
            bulletin_id: Database ID of the saved bulletin.

        Returns:
            List of EditorialCommentChunk objects.
        """
        chunks = []

        # Extract the main content as one chunk
        if bulletin.content:
            chunks.append(
                EditorialCommentChunk(
                    source_type="bulletin",
                    source_id=bulletin_id,
                    source_date=bulletin.issue_date,
                    category=None,
                    content=bulletin.content,
                )
            )

        # If content has clear paragraph breaks, split into separate chunks
        paragraphs = [p.strip() for p in bulletin.content.split("\n\n") if p.strip()]
        if len(paragraphs) > 2:
            # Reset and use paragraphs as chunks instead
            chunks = []
            for i, para in enumerate(paragraphs):
                if len(para) > 100:
                    chunks.append(
                        EditorialCommentChunk(
                            source_type="bulletin",
                            source_id=bulletin_id,
                            source_date=bulletin.issue_date,
                            category=f"paragraph_{i + 1}",
                            content=para,
                        )
                    )

        log.info("extracted_editorial_comments", count=len(chunks), bulletin_id=bulletin_id)
        return chunks
