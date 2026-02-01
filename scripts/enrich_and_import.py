# ABOUTME: Script to enrich January 2026 backfill articles and import directly to PostgreSQL.
# ABOUTME: Handles interruptions gracefully by skipping already-imported articles.

import asyncio
import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import structlog

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from sqlalchemy import select, text

from behind_bars_pulse.ai.service import AIService
from behind_bars_pulse.config import get_settings
from behind_bars_pulse.db.models import Article
from behind_bars_pulse.db.session import close_db, get_engine, get_session
from behind_bars_pulse.models import Article as ArticleModel

log = structlog.get_logger()

BACKFILL_FILE = (
    Path(__file__).parent.parent / "data" / "collected_articles" / "2026-01-january-backfill.json"
)
BATCH_SIZE = 5  # Articles per AI batch
AI_DELAY = 2.0  # Seconds between AI calls


async def init_db_extensions():
    """Ensure pgvector extension exists."""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    log.info("db_extensions_ready")


async def get_existing_links() -> set[str]:
    """Get all article links already in database."""
    async with get_session() as session:
        result = await session.execute(select(Article.link))
        return {row[0] for row in result.fetchall()}


async def enrich_article(ai_service: AIService, article: dict) -> dict | None:
    """Enrich a single article with AI-generated summary and category."""
    try:
        # Create Article model for AI service
        article_model = ArticleModel(
            title=article["title"],
            link=article["link"],
            content=article["content"][:5000],  # Limit content for AI
        )

        # Enrich with AI - expects dict[str, Article]
        articles_dict = {article["link"]: article_model}
        enriched_dict = ai_service.enrich_articles(articles_dict)

        if not enriched_dict:
            return None

        enriched = enriched_dict.get(article["link"])
        if not enriched:
            return None

        return {
            "title": enriched.title,
            "link": str(enriched.link),
            "content": article["content"],  # Keep full content
            "author": enriched.author or article.get("author"),
            "source": enriched.source or article.get("source", "Ristretti Orizzonti"),
            "summary": enriched.summary,
            "published_date": article.get("published_date"),
        }

    except Exception as e:
        log.error("enrich_failed", link=article["link"], error=str(e))
        return None


async def save_article(session, article: dict) -> bool:
    """Save a single article to the database."""
    try:
        pub_date = None
        if article.get("published_date"):
            pub_date = date.fromisoformat(article["published_date"])

        db_article = Article(
            title=article["title"],
            link=article["link"],
            content=article["content"],
            author=article.get("author"),
            source=article.get("source"),
            summary=article.get("summary"),
            published_date=pub_date,
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )

        session.add(db_article)
        await session.flush()
        return True

    except Exception as e:
        log.error("save_failed", link=article["link"], error=str(e))
        await session.rollback()
        return False


async def main():
    _ = get_settings()  # Initialize settings (validates configuration)

    # Load backfill data
    log.info("loading_backfill", file=str(BACKFILL_FILE))
    with open(BACKFILL_FILE) as f:
        articles = list(json.load(f).values())
    log.info("loaded_articles", count=len(articles))

    # Initialize DB
    await init_db_extensions()

    # Get existing articles to skip
    existing_links = await get_existing_links()
    log.info("existing_articles", count=len(existing_links))

    # Filter out already imported
    to_process = [a for a in articles if a["link"] not in existing_links]
    log.info("articles_to_process", count=len(to_process), skipped=len(articles) - len(to_process))

    if not to_process:
        log.info("nothing_to_do")
        return

    # Initialize AI service
    ai_service = AIService()

    # Process in batches
    success_count = 0
    error_count = 0

    for i in range(0, len(to_process), BATCH_SIZE):
        batch = to_process[i : i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        total_batches = (len(to_process) + BATCH_SIZE - 1) // BATCH_SIZE

        log.info("processing_batch", batch=batch_num, total=total_batches, size=len(batch))

        async with get_session() as session:
            for article in batch:
                # Enrich with AI
                enriched = await enrich_article(ai_service, article)

                if enriched:
                    # Save to DB
                    if await save_article(session, enriched):
                        success_count += 1
                        log.info("article_saved", title=enriched["title"][:50], total=success_count)
                    else:
                        error_count += 1
                else:
                    # Save without enrichment as fallback
                    if await save_article(session, article):
                        success_count += 1
                        log.info(
                            "article_saved_raw", title=article["title"][:50], total=success_count
                        )
                    else:
                        error_count += 1

                # Rate limiting for AI
                await asyncio.sleep(AI_DELAY)

            # Commit batch
            await session.commit()

        log.info("batch_complete", batch=batch_num, success=success_count, errors=error_count)

    log.info("import_complete", success=success_count, errors=error_count)

    # Cleanup
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
