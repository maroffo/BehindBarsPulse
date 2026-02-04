# ABOUTME: Regenerate article embeddings with the new embedding model.
# ABOUTME: One-time script to update embeddings after model change.

import asyncio
import time

import structlog
from google import genai
from sqlalchemy import select, update

from behind_bars_pulse.config import get_settings
from behind_bars_pulse.db.models import Article
from behind_bars_pulse.db.session import get_session

log = structlog.get_logger()

EMBEDDING_MODEL = "models/text-embedding-004"
BATCH_SIZE = 50
SLEEP_BETWEEN_BATCHES = 2  # seconds


def generate_embedding(client: genai.Client, text: str) -> list[float]:
    """Generate embedding for text."""
    response = client.models.embed_content(
        model=EMBEDDING_MODEL,
        contents=text,
    )
    return response.embeddings[0].values


async def main():
    settings = get_settings()
    if not settings.gemini_api_key:
        log.error("GEMINI_API_KEY not set")
        return

    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())

    async with get_session() as session:
        # Get all articles
        result = await session.execute(select(Article).order_by(Article.id))
        articles = list(result.scalars().all())

        log.info("articles_found", count=len(articles))

        updated = 0
        errors = 0

        for i, article in enumerate(articles):
            # Build text for embedding
            text = article.title
            if article.summary:
                text = f"{article.title}. {article.summary}"

            try:
                embedding = generate_embedding(client, text)

                # Update article embedding
                await session.execute(
                    update(Article).where(Article.id == article.id).values(embedding=embedding)
                )
                updated += 1

                if (i + 1) % 10 == 0:
                    log.info("progress", current=i + 1, total=len(articles), updated=updated)

                # Rate limiting
                if (i + 1) % BATCH_SIZE == 0:
                    await session.commit()
                    log.info("batch_committed", batch=i // BATCH_SIZE + 1)
                    time.sleep(SLEEP_BETWEEN_BATCHES)

            except Exception as e:
                log.warning("embedding_failed", article_id=article.id, error=str(e))
                errors += 1

        # Final commit
        await session.commit()

    log.info("regeneration_complete", updated=updated, errors=errors)


if __name__ == "__main__":
    asyncio.run(main())
