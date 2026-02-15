# ABOUTME: Weekly digest generator and pipeline for BehindBarsPulse.
# ABOUTME: Synthesizes daily bulletins into a weekly summary, saves to DB, returns results.

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import structlog

from behind_bars_pulse.ai.prompts import WEEKLY_DIGEST_PROMPT
from behind_bars_pulse.ai.service import AIService
from behind_bars_pulse.config import Settings, get_settings
from behind_bars_pulse.models import NewsletterContext
from behind_bars_pulse.narrative.models import NarrativeContext
from behind_bars_pulse.narrative.storage import NarrativeStorage

log = structlog.get_logger()


class WeeklyDigestContent:
    """Content for a weekly digest newsletter."""

    def __init__(
        self,
        weekly_title: str,
        weekly_subtitle: str,
        narrative_arcs: list[dict[str, Any]],
        weekly_reflection: str,
        upcoming_events: list[dict[str, Any]],
    ) -> None:
        self.weekly_title = weekly_title
        self.weekly_subtitle = weekly_subtitle
        self.narrative_arcs = narrative_arcs
        self.weekly_reflection = weekly_reflection
        self.upcoming_events = upcoming_events


class WeeklyDigestGenerator:
    """Generates weekly digest from daily bulletins and narrative context."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.ai_service = AIService(self.settings)
        self.storage = NarrativeStorage(self.settings)

    def generate(
        self,
        bulletins: list[Any],
        reference_date: date | None = None,
    ) -> WeeklyDigestContent:
        """Generate weekly digest content from daily bulletins.

        Args:
            bulletins: List of Bulletin ORM objects from the past week.
            reference_date: End date of the period. Defaults to today.

        Returns:
            WeeklyDigestContent with generated weekly summary.
        """
        reference_date = reference_date or date.today()

        log.info(
            "generating_weekly_digest",
            bulletin_count=len(bulletins),
            reference_date=reference_date.isoformat(),
        )

        if not bulletins:
            raise ValueError("No bulletins found for weekly digest")

        daily_summaries = self._build_summaries_from_bulletins(bulletins)
        log.info("daily_summaries_loaded", count=len(daily_summaries))

        # Load narrative context
        narrative_context = self.storage.load_context()
        log.info(
            "narrative_context_for_weekly",
            stories=len(narrative_context.ongoing_storylines),
            characters=len(narrative_context.key_characters),
        )

        # Generate weekly digest content
        prompt_data = self._build_prompt_data(daily_summaries, narrative_context, reference_date)

        response = self.ai_service._generate(
            prompt=json.dumps(prompt_data, indent=2, ensure_ascii=False),
            system_prompt=WEEKLY_DIGEST_PROMPT,
        )

        result = json.loads(response)
        log.info("weekly_digest_generated")

        return WeeklyDigestContent(
            weekly_title=result.get("weekly_title", "Digest Settimanale"),
            weekly_subtitle=result.get("weekly_subtitle", ""),
            narrative_arcs=result.get("narrative_arcs", []),
            weekly_reflection=result.get("weekly_reflection", ""),
            upcoming_events=result.get("upcoming_events", []),
        )

    def _build_summaries_from_bulletins(
        self,
        bulletins: list[Any],
    ) -> list[dict[str, Any]]:
        """Build daily summary dicts from Bulletin ORM objects.

        Args:
            bulletins: List of Bulletin objects with issue_date, title,
                subtitle, content, press_review fields.

        Returns:
            List of summary dicts sorted by date ascending.
        """
        summaries = []
        for bulletin in bulletins:
            press_categories = []
            if bulletin.press_review:
                for cat in bulletin.press_review:
                    press_categories.append(
                        {
                            "category": cat.get("category", ""),
                            "comment": cat.get("comment", ""),
                        }
                    )

            summaries.append(
                {
                    "date": bulletin.issue_date.isoformat(),
                    "title": bulletin.title,
                    "subtitle": bulletin.subtitle or "",
                    "editorial": bulletin.content,
                    "press_review": press_categories,
                }
            )

        return sorted(summaries, key=lambda x: x["date"])

    def _build_prompt_data(
        self,
        daily_summaries: list[dict[str, Any]],
        narrative_context: NarrativeContext,
        reference_date: date,
    ) -> dict[str, Any]:
        """Build the prompt data for weekly digest generation.

        Args:
            daily_summaries: List of daily bulletin summaries.
            narrative_context: Current narrative context.
            reference_date: Reference date for the digest.

        Returns:
            Dictionary to be JSON-serialized as prompt.
        """
        # Get top stories by mention count
        top_stories = sorted(
            [s for s in narrative_context.ongoing_storylines if s.status == "active"],
            key=lambda s: s.mention_count,
            reverse=True,
        )[:5]

        # Get upcoming events
        upcoming = [
            f
            for f in narrative_context.get_pending_followups()
            if f.expected_date > reference_date
            and f.expected_date <= reference_date + timedelta(days=14)
        ]

        return {
            "daily_summaries": daily_summaries,
            "narrative_context": {
                "top_stories": [
                    {
                        "topic": s.topic,
                        "summary": s.summary,
                        "mention_count": s.mention_count,
                        "impact_score": s.impact_score,
                        "first_seen": s.first_seen.isoformat(),
                        "last_update": s.last_update.isoformat(),
                    }
                    for s in top_stories
                ],
                "key_characters": [
                    {
                        "name": c.name,
                        "role": c.role,
                        "recent_positions": [
                            {"date": p.date.isoformat(), "stance": p.stance}
                            for p in c.positions[-3:]
                        ],
                    }
                    for c in narrative_context.key_characters[:5]
                ],
                "upcoming_events": [
                    {
                        "event": f.event,
                        "expected_date": f.expected_date.isoformat(),
                    }
                    for f in upcoming
                ],
            },
            "reference_date": reference_date.isoformat(),
        }

    def build_email_context(
        self,
        content: WeeklyDigestContent,
        week_start: date,
        week_end: date,
    ) -> dict[str, Any]:
        """Build email template context for weekly digest.

        Args:
            content: Generated weekly digest content.
            week_start: Start date of the week.
            week_end: End date of the week.

        Returns:
            Dict with template variables for weekly_digest_template.
        """
        week_str = f"{week_start.strftime('%d.%m')} - {week_end.strftime('%d.%m.%Y')}"
        subject = f"BehindBars - Digest Settimanale - {week_str}"

        return {
            "subject": subject,
            "week_str": week_str,
            "weekly_title": content.weekly_title,
            "weekly_subtitle": content.weekly_subtitle,
            "narrative_arcs": content.narrative_arcs,
            "weekly_reflection": content.weekly_reflection,
            "upcoming_events": content.upcoming_events,
        }

    def build_context(
        self,
        content: WeeklyDigestContent,
        week_start: date,
        week_end: date,
    ) -> NewsletterContext:
        """Build email context for weekly digest.

        Args:
            content: Generated weekly digest content.
            week_start: Start date of the week.
            week_end: End date of the week.

        Returns:
            NewsletterContext suitable for email rendering.
        """
        week_str = f"{week_start.strftime('%d.%m')} - {week_end.strftime('%d.%m.%Y')}"
        subject = f"⚖️⛓️BehindBars - Digest Settimanale - {week_str}"

        # Format narrative arcs as opening
        opening_parts = []
        for arc in content.narrative_arcs:
            opening_parts.append(f"**{arc.get('arc_title', '')}**\n{arc.get('summary', '')}")

        opening = "\n\n".join(opening_parts) if opening_parts else content.weekly_reflection

        # Format upcoming events as part of closing
        closing_parts = [content.weekly_reflection]
        if content.upcoming_events:
            closing_parts.append("\n\n**Eventi in arrivo:**")
            for event in content.upcoming_events:
                closing_parts.append(f"- {event.get('event', '')} ({event.get('date', '')})")

        closing = "\n".join(closing_parts)

        return NewsletterContext(
            subject=subject,
            today_str=week_str,
            newsletter_title=content.weekly_title,
            newsletter_subtitle=content.weekly_subtitle,
            newsletter_opening=opening,
            newsletter_closing=closing,
            press_review=[],  # Weekly digest doesn't have press review categories
        )


@dataclass
class WeeklyPipelineResult:
    """Result of the weekly digest pipeline."""

    content: WeeklyDigestContent
    email_context: dict[str, Any]
    recipients: list[str]
    week_start: date
    week_end: date


def run_weekly_pipeline(
    reference_date: date,
    settings: Settings | None = None,
) -> WeeklyPipelineResult:
    """Run the full weekly digest pipeline: load data, generate, save to DB.

    Loads bulletins and subscribers from the database, generates the weekly
    digest via AI, saves the digest to DB (replacing any existing one for
    the same week_end), and returns the result for callers to send or preview.

    Raises:
        ValueError: If no bulletins found for the given week.
    """
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session, sessionmaker

    from behind_bars_pulse.config import make_sync_url
    from behind_bars_pulse.db.models import Bulletin as BulletinORM
    from behind_bars_pulse.db.models import Subscriber
    from behind_bars_pulse.db.models import WeeklyDigest as WeeklyDigestORM

    settings = settings or get_settings()
    generator = WeeklyDigestGenerator(settings)
    lookback = generator.settings.weekly_lookback_days
    week_end = reference_date
    week_start = reference_date - timedelta(days=lookback - 1)

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

            recipients = list(
                session.execute(
                    select(Subscriber.email)
                    .where(Subscriber.confirmed == True)  # noqa: E712
                    .where(Subscriber.unsubscribed_at.is_(None))
                )
                .scalars()
                .all()
            )

        log.info("weekly_data_loaded", bulletins=len(bulletins), recipients=len(recipients))

        content = generator.generate(bulletins=bulletins, reference_date=reference_date)
        email_context = generator.build_email_context(content, week_start, week_end)

        # Save WeeklyDigest to DB (atomic: delete + add in one transaction)
        with Session(engine) as session:
            existing = (
                session.query(WeeklyDigestORM).filter(WeeklyDigestORM.week_end == week_end).first()
            )
            if existing:
                session.delete(existing)

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

    return WeeklyPipelineResult(
        content=content,
        email_context=email_context,
        recipients=recipients,
        week_start=week_start,
        week_end=week_end,
    )
