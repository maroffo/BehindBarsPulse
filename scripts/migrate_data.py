#!/usr/bin/env python
# ABOUTME: Data migration script to populate database from existing files.
# ABOUTME: Migrates previous_issues, collected_articles, and narrative_context to PostgreSQL.

"""
Data Migration Script

Migrates existing data to the PostgreSQL database:
1. previous_issues/*.txt → newsletters table
2. data/collected_articles/*.json → articles table
3. data/narrative_context.json → story_threads, key_characters, followups tables

Usage:
    uv run python scripts/migrate_data.py [--skip-embeddings] [--dry-run]
"""

import argparse
import asyncio
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from behind_bars_pulse.config import get_settings
from behind_bars_pulse.db.models import (
    Article,
    CharacterPosition,
    FollowUp,
    KeyCharacter,
    Newsletter,
    StoryThread,
)
from behind_bars_pulse.db.session import get_session, init_db
from behind_bars_pulse.services.newsletter_service import NewsletterService

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
logger = structlog.get_logger()


def parse_newsletter_txt(file_path: Path) -> dict | None:
    """Parse a newsletter txt file into structured data."""
    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("file_read_error", path=str(file_path), error=str(e))
        return None

    # Extract date from filename (YYYYMMDD.txt)
    date_str = file_path.stem
    if "_" in date_str:
        date_str = date_str.split("_")[0]

    try:
        issue_date = datetime.strptime(date_str, "%Y%m%d").date()
    except ValueError:
        logger.error("invalid_date_format", path=str(file_path), date_str=date_str)
        return None

    lines = content.split("\n")

    result = {
        "issue_date": issue_date,
        "title": "",
        "subtitle": "",
        "opening": "",
        "closing": "",
        "txt_content": content,
    }

    for line in lines:
        line = line.strip()
        if line.startswith("Title:"):
            result["title"] = line[6:].strip()
        elif line.startswith("Subtitle:"):
            result["subtitle"] = line[9:].strip()
        elif line.startswith("Opening Comment:"):
            result["opening"] = line[16:].strip()
        elif line.startswith("Closing Comment:"):
            result["closing"] = line[16:].strip()

    # Validate required fields
    if not result["title"]:
        logger.warning("missing_title", path=str(file_path))
        result["title"] = f"Newsletter {issue_date.strftime('%d/%m/%Y')}"

    return result


async def migrate_newsletters(session: AsyncSession, dry_run: bool = False) -> int:
    """Migrate previous_issues/*.txt to newsletters table."""
    settings = get_settings()
    issues_dir = Path(settings.previous_issues_dir)

    if not issues_dir.exists():
        logger.warning("issues_dir_not_found", path=str(issues_dir))
        return 0

    txt_files = sorted(issues_dir.glob("*.txt"))
    logger.info("found_newsletter_files", count=len(txt_files))

    migrated = 0
    for file_path in txt_files:
        data = parse_newsletter_txt(file_path)
        if not data:
            continue

        if dry_run:
            logger.info("dry_run_newsletter", issue_date=data["issue_date"])
            migrated += 1
            continue

        newsletter = Newsletter(
            issue_date=data["issue_date"],
            title=data["title"],
            subtitle=data["subtitle"] or "Newsletter quotidiana",
            opening=data["opening"] or "",
            closing=data["closing"] or "",
            txt_content=data["txt_content"],
            created_at=datetime.utcnow(),
        )
        session.add(newsletter)
        migrated += 1
        logger.info("newsletter_migrated", issue_date=data["issue_date"])

    await session.flush()
    logger.info("newsletters_migration_complete", total=migrated)
    return migrated


async def migrate_articles(
    session: AsyncSession,
    newsletter_service: NewsletterService | None,
    skip_embeddings: bool = False,
    dry_run: bool = False,
) -> int:
    """Migrate data/collected_articles/*.json to articles table."""
    settings = get_settings()
    articles_dir = Path(settings.data_dir) / "collected_articles"

    if not articles_dir.exists():
        logger.warning("articles_dir_not_found", path=str(articles_dir))
        return 0

    json_files = sorted(articles_dir.glob("*.json"))
    logger.info("found_article_files", count=len(json_files))

    migrated = 0
    for file_path in json_files:
        # Extract date from filename (YYYY-MM-DD.json)
        date_str = file_path.stem
        try:
            published_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            logger.warning("invalid_article_date", path=str(file_path))
            continue

        try:
            with open(file_path, encoding="utf-8") as f:
                articles_data = json.load(f)
        except Exception as e:
            logger.error("json_parse_error", path=str(file_path), error=str(e))
            continue

        articles_to_save = []
        for link, article_data in articles_data.items():
            if dry_run:
                logger.debug("dry_run_article", link=link)
                migrated += 1
                continue

            article = Article(
                title=article_data.get("title", "Untitled"),
                link=link,
                content=article_data.get("content", ""),
                author=article_data.get("author") or None,
                source=article_data.get("source") or None,
                summary=article_data.get("summary") or None,
                published_date=published_date,
                created_at=datetime.utcnow(),
            )
            articles_to_save.append(article)
            migrated += 1

        if articles_to_save and not dry_run:
            session.add_all(articles_to_save)
            await session.flush()

            # Generate embeddings if requested
            if not skip_embeddings and newsletter_service:
                await _generate_embeddings_batch(
                    session, newsletter_service, articles_to_save
                )

        logger.info(
            "articles_batch_migrated", date=date_str, count=len(articles_to_save)
        )

    logger.info("articles_migration_complete", total=migrated)
    return migrated


async def _generate_embeddings_batch(
    session: AsyncSession,
    newsletter_service: NewsletterService,
    articles: list[Article],
) -> None:
    """Generate embeddings for a batch of articles."""
    for article in articles:
        text = article.title
        if article.summary:
            text = f"{article.title}. {article.summary}"

        try:
            embedding = await newsletter_service.generate_embedding(text)
            article.embedding = embedding
            logger.debug("embedding_generated", article_id=article.id)
            await asyncio.sleep(0.1)  # Rate limiting
        except Exception as e:
            logger.error("embedding_failed", article_id=article.id, error=str(e))

    await session.flush()


async def migrate_narrative(session: AsyncSession, dry_run: bool = False) -> dict[str, int]:
    """Migrate data/narrative_context.json to story_threads, key_characters, followups."""
    settings = get_settings()
    context_file = Path(settings.data_dir) / settings.narrative_context_file

    if not context_file.exists():
        logger.warning("narrative_context_not_found", path=str(context_file))
        return {"stories": 0, "characters": 0, "followups": 0}

    try:
        with open(context_file, encoding="utf-8") as f:
            context = json.load(f)
    except Exception as e:
        logger.error("json_parse_error", path=str(context_file), error=str(e))
        return {"stories": 0, "characters": 0, "followups": 0}

    counts = {"stories": 0, "characters": 0, "followups": 0}

    # Migrate story threads
    for story_data in context.get("ongoing_storylines", []):
        if dry_run:
            logger.debug("dry_run_story", topic=story_data.get("topic"))
            counts["stories"] += 1
            continue

        story = StoryThread(
            id=story_data["id"],
            topic=story_data["topic"],
            status=story_data.get("status", "active"),
            first_seen=datetime.strptime(story_data["first_seen"], "%Y-%m-%d").date(),
            last_update=datetime.strptime(story_data["last_update"], "%Y-%m-%d").date(),
            summary=story_data["summary"],
            keywords=story_data.get("keywords", []),
            related_articles=story_data.get("related_articles", []),
            mention_count=story_data.get("mention_count", 1),
            impact_score=story_data.get("impact_score", 0.0),
            weekly_highlight=story_data.get("weekly_highlight", False),
            created_at=datetime.utcnow(),
        )
        session.add(story)
        counts["stories"] += 1

    # Migrate key characters
    for char_data in context.get("key_characters", []):
        if dry_run:
            logger.debug("dry_run_character", name=char_data.get("name"))
            counts["characters"] += 1
            continue

        character = KeyCharacter(
            name=char_data["name"],
            role=char_data["role"],
            aliases=char_data.get("aliases", []),
            created_at=datetime.utcnow(),
        )
        session.add(character)
        await session.flush()

        # Migrate positions
        for pos_data in char_data.get("positions", []):
            position = CharacterPosition(
                character_id=character.id,
                position_date=datetime.strptime(pos_data["date"], "%Y-%m-%d").date(),
                stance=pos_data["stance"],
                source_url=pos_data.get("source_url"),
                created_at=datetime.utcnow(),
            )
            session.add(position)

        counts["characters"] += 1

    # Migrate follow-ups
    for followup_data in context.get("pending_followups", []):
        if dry_run:
            logger.debug("dry_run_followup", event=followup_data.get("event"))
            counts["followups"] += 1
            continue

        followup = FollowUp(
            id=followup_data["id"],
            event=followup_data["event"],
            expected_date=datetime.strptime(followup_data["expected_date"], "%Y-%m-%d").date(),
            story_id=followup_data.get("story_id"),
            created_at=datetime.strptime(followup_data["created_at"], "%Y-%m-%d").date(),
            resolved=followup_data.get("resolved", False),
        )
        session.add(followup)
        counts["followups"] += 1

    await session.flush()
    logger.info("narrative_migration_complete", **counts)
    return counts


async def main(skip_embeddings: bool = False, dry_run: bool = False) -> None:
    """Run all migrations."""
    logger.info(
        "starting_migration",
        skip_embeddings=skip_embeddings,
        dry_run=dry_run,
    )

    if not dry_run:
        # Initialize database tables
        await init_db()
        logger.info("database_initialized")

    newsletter_service = None if skip_embeddings else NewsletterService()

    async with get_session() as session:
        # Migrate newsletters
        newsletters_count = await migrate_newsletters(session, dry_run)

        # Migrate articles
        articles_count = await migrate_articles(
            session, newsletter_service, skip_embeddings, dry_run
        )

        # Migrate narrative context
        narrative_counts = await migrate_narrative(session, dry_run)

        if dry_run:
            logger.info("dry_run_complete")
        else:
            await session.commit()
            logger.info("migration_complete")

        logger.info(
            "summary",
            newsletters=newsletters_count,
            articles=articles_count,
            **narrative_counts,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate data to PostgreSQL database")
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="Skip generating embeddings for articles",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without writing to database",
    )
    args = parser.parse_args()

    asyncio.run(main(skip_embeddings=args.skip_embeddings, dry_run=args.dry_run))
