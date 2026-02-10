# ABOUTME: Weekly digest generator for BehindBarsPulse.
# ABOUTME: Synthesizes daily bulletins into a weekly summary using narrative context.

import json
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
