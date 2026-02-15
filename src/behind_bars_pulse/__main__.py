# ABOUTME: CLI entry point for BehindBarsPulse newsletter system.
# ABOUTME: Provides subcommands: collect, generate, weekly, status.

import argparse
import logging
import sys
from datetime import date

import structlog

from behind_bars_pulse.config import get_settings, make_sync_url


def configure_logging() -> None:
    """Configure structlog for console or JSON output."""
    settings = get_settings()

    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    if settings.log_format == "json":
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
        )
    else:
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
                structlog.processors.add_log_level,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            wrapper_class=structlog.make_filtering_bound_logger(log_level),
        )


def _handle_gcp_auth_error(e: Exception, log: structlog.BoundLogger) -> bool:
    """Check if exception is a GCP auth error and log friendly message.

    Returns True if it was an auth error, False otherwise.
    """
    error_str = str(e)
    if "Reauthentication is needed" in error_str or "RefreshError" in type(e).__name__:
        log.error(
            "gcp_auth_required",
            hint="Run: gcloud auth application-default login",
        )
        print("\n⚠️  Google Cloud authentication required.")
        print("   Run: gcloud auth application-default login\n")
        return True
    return False


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

    except Exception as e:
        if _handle_gcp_auth_error(e, log):
            return 1
        log.exception("cmd_collect_failed")
        return 1


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate daily newsletter and archive it.

    Uses collected articles if available, otherwise fetches fresh.
    Integrates narrative context when available.
    Always archives without sending - use 'weekly' command to send.
    """
    from behind_bars_pulse.email.sender import EmailSender
    from behind_bars_pulse.newsletter.generator import NewsletterGenerator

    log = structlog.get_logger()
    log.info("cmd_generate_start")

    collection_date = date.fromisoformat(args.date) if args.date else date.today()
    days_back = args.days_back

    first_issue = getattr(args, "first_issue", False)

    try:
        with NewsletterGenerator() as generator:
            newsletter_content, press_review, enriched_articles = generator.generate(
                collection_date=collection_date,
                days_back=days_back,
                first_issue=first_issue,
            )

            today_str = collection_date.strftime("%d.%m.%Y")
            context = generator.build_context(newsletter_content, press_review, today_str)

            # Always archive (never send directly - use 'weekly' command for sending)
            sender = EmailSender()
            preview_path = sender.save_preview(context, issue_date=collection_date)
            log.info(
                "newsletter_archived", title=newsletter_content.title, preview=str(preview_path)
            )

        log.info("cmd_generate_complete")
        return 0

    except Exception as e:
        if _handle_gcp_auth_error(e, log):
            return 1
        log.exception("cmd_generate_failed")
        return 1


def cmd_weekly(args: argparse.Namespace) -> int:
    """Generate and send weekly digest to subscribers.

    Summarizes the past week's bulletins using narrative context.
    Fetches bulletins and active subscribers from database.
    """
    from datetime import timedelta

    from behind_bars_pulse.email.sender import EmailSender
    from behind_bars_pulse.newsletter.weekly import WeeklyDigestGenerator

    log = structlog.get_logger()
    log.info("cmd_weekly_start")

    reference_date = date.fromisoformat(args.date) if args.date else date.today()

    try:
        generator = WeeklyDigestGenerator()
        lookback = generator.settings.weekly_lookback_days
        week_end = reference_date
        week_start = reference_date - timedelta(days=lookback - 1)

        # Load bulletins from DB (sync)
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session, sessionmaker

        from behind_bars_pulse.db.models import Bulletin as BulletinORM
        from behind_bars_pulse.db.models import WeeklyDigest as WeeklyDigestORM

        settings = get_settings()
        sync_url = make_sync_url(settings.database_url)
        engine = create_engine(sync_url)
        try:
            SessionLocal = sessionmaker(bind=engine)

            with SessionLocal() as session:
                bulletins = list(
                    session.execute(
                        select(BulletinORM)
                        .where(
                            BulletinORM.issue_date >= week_start,
                            BulletinORM.issue_date <= week_end,
                        )
                        .order_by(BulletinORM.issue_date.asc())
                    )
                    .scalars()
                    .all()
                )

            log.info("bulletins_loaded", count=len(bulletins))

            content = generator.generate(bulletins=bulletins, reference_date=reference_date)
            email_context = generator.build_email_context(content, week_start, week_end)

            # Save WeeklyDigest to DB
            with Session(engine) as session:
                existing = (
                    session.query(WeeklyDigestORM)
                    .filter(WeeklyDigestORM.week_end == week_end)
                    .first()
                )
                if existing:
                    session.delete(existing)
                    session.commit()

                digest = WeeklyDigestORM(
                    week_start=week_start,
                    week_end=week_end,
                    title=content.weekly_title,
                    subtitle=content.weekly_subtitle or None,
                    narrative_arcs=content.narrative_arcs,
                    weekly_reflection=content.weekly_reflection,
                    upcoming_events=content.upcoming_events,
                )
                session.add(digest)
                session.commit()
                log.info("weekly_digest_saved", week_end=week_end.isoformat(), id=digest.id)
        finally:
            engine.dispose()

        if not args.dry_run:
            # Fetch recipients (sync, same pattern as _run_weekly in api.py)
            from behind_bars_pulse.db.models import Subscriber

            sync_engine = create_engine(sync_url)
            try:
                with Session(sync_engine) as session:
                    recipients = list(
                        session.execute(
                            select(Subscriber.email)
                            .where(Subscriber.confirmed == True)  # noqa: E712
                            .where(Subscriber.unsubscribed_at.is_(None))
                        )
                        .scalars()
                        .all()
                    )
            finally:
                sync_engine.dispose()

            if not recipients:
                log.warning("no_active_subscribers")
                print("\nNo active subscribers found in database.\n")
                return 0

            log.info("sending_to_subscribers", count=len(recipients))
            sender = EmailSender()
            sender.send(
                email_context,
                recipients=recipients,
                html_template="weekly_digest_template.html",
                txt_template="weekly_digest_template.txt",
            )
            log.info("weekly_digest_sent", recipient_count=len(recipients))
        else:
            # Preview mode
            sender = EmailSender()
            preview_path = sender.save_preview(
                email_context,
                issue_date=reference_date,
                html_template="weekly_digest_template.html",
                txt_template="weekly_digest_template.txt",
            )
            log.info(
                "weekly_dry_run_complete", title=content.weekly_title, preview=str(preview_path)
            )

        log.info("cmd_weekly_complete")
        return 0

    except ValueError as e:
        log.error("weekly_generation_failed", error=str(e))
        return 1
    except Exception as e:
        if _handle_gcp_auth_error(e, log):
            return 1
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
        help="Generate and archive daily newsletter (does not send)",
    )
    generate_parser.add_argument(
        "--date",
        type=str,
        help="End date for article collection (YYYY-MM-DD). Defaults to today.",
    )
    generate_parser.add_argument(
        "--days-back",
        type=int,
        default=7,
        help="Number of days to look back for articles (default: 7)",
    )
    generate_parser.add_argument(
        "--first-issue",
        action="store_true",
        help="Include introductory text for the first newsletter edition",
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
        # Default behavior: run generate (archive only)
        args.date = None
        args.days_back = 7
        args.first_issue = False
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
