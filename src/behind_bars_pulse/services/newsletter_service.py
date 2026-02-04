# ABOUTME: Service for persisting newsletters and articles to the database.
# ABOUTME: Integrates with Gemini API for embedding generation.

import asyncio
from datetime import UTC, date, datetime

import structlog
from google import genai
from google.genai.types import EmbedContentConfig

from behind_bars_pulse.config import get_settings
from behind_bars_pulse.db.models import Article as ArticleModel
from behind_bars_pulse.db.models import Newsletter as NewsletterModel
from behind_bars_pulse.db.repository import ArticleRepository, NewsletterRepository
from behind_bars_pulse.db.session import get_session
from behind_bars_pulse.models import EnrichedArticle, NewsletterContext, PressReviewCategory

logger = structlog.get_logger()

EMBEDDING_MODEL = "models/text-embedding-004"


class NewsletterService:
    """Service for newsletter persistence and embedding generation."""

    def __init__(self) -> None:
        self._genai_client: genai.Client | None = None

    @property
    def genai_client(self) -> genai.Client:
        """Lazy-init Gemini client."""
        if self._genai_client is None:
            settings = get_settings()
            if not settings.gemini_api_key:
                raise ValueError("GEMINI_API_KEY is required for embeddings")
            self._genai_client = genai.Client(
                api_key=settings.gemini_api_key.get_secret_value(),
            )
        return self._genai_client

    async def save_newsletter(
        self,
        context: NewsletterContext,
        enriched_articles: list[EnrichedArticle],
        press_review: list[PressReviewCategory],
        html_content: str | None = None,
        txt_content: str | None = None,
        issue_date: date | None = None,
        generate_embeddings: bool = True,
    ) -> NewsletterModel:
        """Save a newsletter with its articles to the database.

        Args:
            context: Newsletter context with generated content
            enriched_articles: List of enriched articles to persist
            press_review: Press review categories with article rankings
            html_content: Rendered HTML content
            txt_content: Rendered plain text content
            issue_date: Override issue date (defaults to today)
            generate_embeddings: Whether to generate embeddings for articles

        Returns:
            Saved Newsletter model instance
        """
        issue_date = issue_date or date.today()

        async with get_session() as session:
            newsletter_repo = NewsletterRepository(session)
            article_repo = ArticleRepository(session)

            # Check if newsletter already exists for this date
            existing = await newsletter_repo.get_by_date(issue_date)
            if existing:
                logger.warning("newsletter_exists", issue_date=issue_date, id=existing.id)
                await newsletter_repo.delete_by_date(issue_date)

            # Create newsletter record
            newsletter = NewsletterModel(
                issue_date=issue_date,
                title=context.newsletter_title,
                subtitle=context.newsletter_subtitle,
                opening=context.newsletter_opening,
                closing=context.newsletter_closing,
                html_content=html_content,
                txt_content=txt_content,
                press_review=[cat.model_dump() for cat in press_review],
                created_at=datetime.now(UTC),
            )
            newsletter = await newsletter_repo.save(newsletter)
            logger.info("newsletter_saved", id=newsletter.id, issue_date=issue_date)

            # Build category/importance lookup from press review
            article_metadata = self._build_article_metadata(press_review)

            # Create article records
            articles_to_save: list[ArticleModel] = []
            for enriched in enriched_articles:
                link_str = str(enriched.link)
                metadata = article_metadata.get(link_str, {})

                # Skip if article already exists (different newsletter)
                existing_article = await article_repo.get_by_link(link_str)
                if existing_article:
                    logger.debug("article_exists", link=link_str)
                    continue

                article = ArticleModel(
                    title=enriched.title,
                    link=link_str,
                    content=enriched.content,
                    author=enriched.author or None,
                    source=enriched.source or None,
                    summary=enriched.summary or None,
                    category=metadata.get("category"),
                    importance=metadata.get("importance"),
                    published_date=issue_date,
                    newsletter_id=newsletter.id,
                    created_at=datetime.now(UTC),
                )
                articles_to_save.append(article)

            if articles_to_save:
                await article_repo.save_batch(articles_to_save)
                logger.info("articles_saved", count=len(articles_to_save))

            # Generate embeddings asynchronously
            if generate_embeddings and articles_to_save:
                await self._generate_embeddings(session, articles_to_save)

        return newsletter

    def _build_article_metadata(
        self, press_review: list[PressReviewCategory]
    ) -> dict[str, dict[str, str]]:
        """Build lookup of article metadata from press review."""
        metadata: dict[str, dict[str, str]] = {}
        for category in press_review:
            for article in category.articles:
                link_str = str(article.link)
                metadata[link_str] = {
                    "category": category.category,
                    "importance": article.importance.value,
                }
        return metadata

    async def _generate_embeddings(self, session, articles: list[ArticleModel]) -> None:
        """Generate embeddings for articles using Vertex AI.

        Uses title + summary for embedding, falling back to title only.
        """
        for article in articles:
            # Build text for embedding: title + summary gives best results
            text_for_embedding = article.title
            if article.summary:
                text_for_embedding = f"{article.title}. {article.summary}"

            try:
                # Run in executor to avoid blocking
                embedding = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda t=text_for_embedding: self._embed_text(t),
                )
                article.embedding = embedding
                logger.debug("embedding_generated", article_id=article.id)

                # Rate limiting
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error("embedding_failed", article_id=article.id, error=str(e))
                continue

        await session.flush()
        logger.info("embeddings_generated", count=len(articles))

    def _embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text string."""
        response = self.genai_client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=EmbedContentConfig(
                task_type="RETRIEVAL_DOCUMENT",
                output_dimensionality=768,
            ),
        )
        if not response.embeddings or not response.embeddings[0].values:
            raise ValueError("No embeddings returned from API")
        return list(response.embeddings[0].values)

    async def generate_embedding(self, text: str) -> list[float]:
        """Public method to generate embedding for search queries."""
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._embed_query(text),
        )

    def _embed_query(self, text: str) -> list[float]:
        """Generate embedding for a search query."""
        response = self.genai_client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=768,
            ),
        )
        if not response.embeddings or not response.embeddings[0].values:
            raise ValueError("No embeddings returned from API")
        return list(response.embeddings[0].values)
