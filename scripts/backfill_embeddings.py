# ABOUTME: Backfill embeddings for articles without them.
# ABOUTME: Uses Vertex AI text-multilingual-embedding-002 model.

import asyncio
import sys
from pathlib import Path

import structlog
from sqlalchemy import func, select

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from behind_bars_pulse.db.models import Article
from behind_bars_pulse.db.session import close_db, get_session
from behind_bars_pulse.services.newsletter_service import NewsletterService

log = structlog.get_logger()

BATCH_SIZE = 50
RATE_LIMIT_DELAY = 0.1  # seconds between embeddings


async def count_articles_without_embeddings() -> int:
    """Count articles that need embeddings."""
    async with get_session() as session:
        result = await session.execute(
            select(func.count(Article.id)).where(Article.embedding.is_(None))
        )
        return result.scalar_one()


async def get_articles_without_embeddings(limit: int) -> list[Article]:
    """Get a batch of articles without embeddings."""
    async with get_session() as session:
        result = await session.execute(
            select(Article).where(Article.embedding.is_(None)).order_by(Article.id).limit(limit)
        )
        return list(result.scalars().all())


async def update_article_embedding(article_id: int, embedding: list[float]) -> None:
    """Update an article's embedding."""
    async with get_session() as session:
        article = await session.get(Article, article_id)
        if article:
            article.embedding = embedding
            await session.commit()


async def main():
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="%H:%M:%S"),
            structlog.processors.add_log_level,
            structlog.dev.ConsoleRenderer(colors=True),
        ],
    )

    # Count articles needing embeddings
    total_missing = await count_articles_without_embeddings()
    log.info("articles_without_embeddings", count=total_missing)

    if total_missing == 0:
        log.info("nothing_to_do")
        return

    # Initialize service
    svc = NewsletterService()
    processed = 0
    errors = 0

    while True:
        # Get batch of articles
        articles = await get_articles_without_embeddings(BATCH_SIZE)
        if not articles:
            break

        batch_num = processed // BATCH_SIZE + 1
        log.info(
            "processing_batch",
            batch=batch_num,
            size=len(articles),
            progress=f"{processed}/{total_missing}",
        )

        for article in articles:
            # Build text for embedding: title + summary
            text = article.title
            if article.summary:
                text = f"{article.title}. {article.summary}"

            try:
                embedding = await svc.generate_embedding(text)
                await update_article_embedding(article.id, embedding)
                processed += 1

                if processed % 10 == 0:
                    log.info("progress", processed=processed, total=total_missing)

                await asyncio.sleep(RATE_LIMIT_DELAY)

            except Exception as e:
                log.error(
                    "embedding_failed",
                    article_id=article.id,
                    title=article.title[:50],
                    error=str(e),
                )
                errors += 1
                continue

    log.info("backfill_complete", processed=processed, errors=errors)
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
