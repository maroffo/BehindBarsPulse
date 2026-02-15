# ABOUTME: Service for generating text embeddings using Gemini API.
# ABOUTME: Provides document and query embedding methods for vector search.

import asyncio

import structlog
from google import genai
from google.genai.types import EmbedContentConfig

from behind_bars_pulse.config import get_settings
from behind_bars_pulse.db.models import Article as ArticleModel

logger = structlog.get_logger()

EMBEDDING_MODEL = "models/gemini-embedding-001"


class EmbeddingService:
    """Service for generating text embeddings via Gemini API."""

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

    def _embed(self, text: str, task_type: str) -> list[float]:
        """Generate embedding for text with specified task type."""
        response = self.genai_client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=EmbedContentConfig(
                task_type=task_type,
                output_dimensionality=768,
            ),
        )
        if not response.embeddings or not response.embeddings[0].values:
            raise ValueError("No embeddings returned from API")
        return list(response.embeddings[0].values)

    def _embed_text(self, text: str) -> list[float]:
        """Generate embedding for a document text."""
        return self._embed(text, "RETRIEVAL_DOCUMENT")

    def _embed_query(self, text: str) -> list[float]:
        """Generate embedding for a search query."""
        return self._embed(text, "RETRIEVAL_QUERY")

    async def generate_embedding(self, text: str) -> list[float]:
        """Public method to generate embedding for search queries."""
        return await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: self._embed_query(text),
        )

    async def _generate_embeddings(self, session, articles: list[ArticleModel]) -> None:
        """Generate embeddings for articles using Gemini API.

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
