# ABOUTME: CLI entry point for BehindBarsPulse newsletter system.
# ABOUTME: Provides subcommands: collect, generate, weekly, status.

import argparse
import sys
from datetime import date

import structlog

from behind_bars_pulse.config import get_settings


def configure_logging() -> None:
    """Configure structlog for console or JSON output."""
    settings = get_settings()

    if settings.log_format == "json":
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(structlog, settings.log_level, structlog.INFO)
            ),
        )
    else:
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
                structlog.processors.add_log_level,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(
                getattr(structlog, settings.log_level, structlog.INFO)
            ),
        )


def cmd_collect(args: argparse.Namespace) -> int:
    """Run daily article collection.

    Fetches RSS, enriches articles, saves to data/collected_articles/.
    """
    from behind_bars_pulse.collector import ArticleCollector

    log = structlog.get_logger()
    log.info("cmd_collect_start")

    collection_date = date.fromisoformat(args.date) if args.date else date.today()

    try:
        with ArticleCollector() as collector:
            enriched = collector.collect(collection_date)

        log.info("cmd_collect_complete", articles=len(enriched))
        return 0

    except Exception:
        log.exception("cmd_collect_failed")
        return 1


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate and send daily newsletter.

    Uses collected articles if available, otherwise fetches fresh.
    Integrates narrative context when available.
    """
    from behind_bars_pulse.email.sender import EmailSender
    from behind_bars_pulse.newsletter.generator import NewsletterGenerator

    log = structlog.get_logger()
    log.info("cmd_generate_start")

    try:
        with NewsletterGenerator() as generator:
            newsletter_content, press_review, _ = generator.generate()

            today_str = date.today().strftime("%d.%m.%Y")
            context = generator.build_context(newsletter_content, press_review, today_str)

            if not args.dry_run:
                sender = EmailSender()
                sender.send(context)
                log.info("newsletter_sent")
            else:
                log.info("dry_run_complete", title=newsletter_content.title)

        log.info("cmd_generate_complete")
        return 0

    except Exception:
        log.exception("cmd_generate_failed")
        return 1


def cmd_weekly(args: argparse.Namespace) -> int:
    """Generate and send weekly digest.

    Summarizes the past week's newsletters using narrative context.
    """
    from datetime import timedelta

    from behind_bars_pulse.email.sender import EmailSender
    from behind_bars_pulse.newsletter.weekly import WeeklyDigestGenerator

    log = structlog.get_logger()
    log.info("cmd_weekly_start")

    reference_date = date.fromisoformat(args.date) if args.date else date.today()

    try:
        generator = WeeklyDigestGenerator()
        content = generator.generate(reference_date=reference_date)

        week_end = reference_date
        week_start = reference_date - timedelta(days=generator.settings.weekly_lookback_days - 1)
        context = generator.build_context(content, week_start, week_end)

        if not args.dry_run:
            sender = EmailSender()
            sender.send(context)
            log.info("weekly_digest_sent")
        else:
            log.info("weekly_dry_run_complete", title=content.weekly_title)

        log.info("cmd_weekly_complete")
        return 0

    except ValueError as e:
        log.error("weekly_generation_failed", error=str(e))
        return 1
    except Exception:
        log.exception("cmd_weekly_failed")
        return 1


def cmd_status(_args: argparse.Namespace) -> int:
    """Show narrative context status.

    Displays active stories, characters, and pending follow-ups.
    """
    from behind_bars_pulse.narrative.storage import NarrativeStorage

    storage = NarrativeStorage()
    context = storage.load_context()

    active_stories = context.get_active_stories()
    dormant_stories = context.get_dormant_stories()
    pending_followups = context.get_pending_followups()
    due_followups = context.get_due_followups(date.today())

    print("\n=== BehindBarsPulse Narrative Status ===\n")

    print(f"Active Stories: {len(active_stories)}")
    for story in active_stories[:5]:
        print(
            f"  - {story.topic} (mentions: {story.mention_count}, impact: {story.impact_score:.2f})"
        )

    print(f"\nDormant Stories: {len(dormant_stories)}")
    for story in dormant_stories[:3]:
        print(f"  - {story.topic} (last update: {story.last_update})")

    print(f"\nKey Characters: {len(context.key_characters)}")
    for char in context.key_characters[:5]:
        print(f"  - {char.name} ({char.role})")

    print(f"\nPending Follow-ups: {len(pending_followups)}")
    for fu in pending_followups[:5]:
        print(f"  - {fu.event} (expected: {fu.expected_date})")

    if due_followups:
        print(f"\n⚠️  Due Follow-ups: {len(due_followups)}")
        for fu in due_followups:
            print(f"  - {fu.event} (was due: {fu.expected_date})")

    collection_dates = storage.get_available_collection_dates()
    print(f"\nCollected Articles: {len(collection_dates)} days")
    if collection_dates:
        print(f"  Latest: {collection_dates[-1]}")
        print(f"  Oldest: {collection_dates[0]}")

    print(f"\nLast Context Update: {context.last_updated}")
    print()

    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser with subcommands."""
    parser = argparse.ArgumentParser(
        prog="behind_bars_pulse",
        description="BehindBarsPulse - Italian prison system newsletter generator",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # collect command
    collect_parser = subparsers.add_parser(
        "collect",
        help="Collect and enrich articles from RSS feed",
    )
    collect_parser.add_argument(
        "--date",
        type=str,
        help="Collection date (YYYY-MM-DD). Defaults to today.",
    )

    # generate command
    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate and send daily newsletter",
    )
    generate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate without sending email",
    )

    # weekly command
    weekly_parser = subparsers.add_parser(
        "weekly",
        help="Generate and send weekly digest",
    )
    weekly_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate without sending email",
    )
    weekly_parser.add_argument(
        "--date",
        type=str,
        help="Reference date for digest (YYYY-MM-DD). Defaults to today.",
    )

    # status command
    subparsers.add_parser(
        "status",
        help="Show narrative context status",
    )

    return parser


def main() -> int:
    """Main entry point."""
    configure_logging()

    parser = create_parser()
    args = parser.parse_args()

    if args.command is None:
        # Default behavior: run generate (backward compatible)
        args.dry_run = False
        return cmd_generate(args)

    commands = {
        "collect": cmd_collect,
        "generate": cmd_generate,
        "weekly": cmd_weekly,
        "status": cmd_status,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
