# ABOUTME: Weekly digest generator for BehindBarsPulse.
# ABOUTME: Synthesizes daily newsletters into a weekly summary using narrative context.

import json
from datetime import date, timedelta
from pathlib import Path
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
    """Generates weekly digest from daily newsletters and narrative context."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.ai_service = AIService(self.settings)
        self.storage = NarrativeStorage(self.settings)

    def generate(
        self,
        lookback_days: int | None = None,
        reference_date: date | None = None,
    ) -> WeeklyDigestContent:
        """Generate weekly digest content.

        Args:
            lookback_days: Number of days to include. Defaults to settings value.
            reference_date: End date of the period. Defaults to today.

        Returns:
            WeeklyDigestContent with generated weekly summary.
        """
        lookback_days = lookback_days or self.settings.weekly_lookback_days
        reference_date = reference_date or date.today()

        log.info(
            "generating_weekly_digest",
            lookback_days=lookback_days,
            reference_date=reference_date.isoformat(),
        )

        # Load daily newsletter summaries
        daily_summaries = self._load_daily_summaries(reference_date, lookback_days)
        if not daily_summaries:
            raise ValueError("No daily newsletters found for weekly digest")

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

    def _load_daily_summaries(
        self,
        reference_date: date,
        lookback_days: int,
    ) -> list[dict[str, Any]]:
        """Load summaries from archived daily newsletters.

        Args:
            reference_date: End date of the period.
            lookback_days: Number of days to look back.

        Returns:
            List of daily summary dicts with date and content.
        """
        summaries = []
        issues_dir = Path(self.settings.previous_issues_dir)

        if not issues_dir.exists():
            return summaries

        for i in range(lookback_days):
            issue_date = reference_date - timedelta(days=i)
            file_name = f"{issue_date.strftime('%Y%m%d')}_issue.txt"
            file_path = issues_dir / file_name

            if file_path.exists():
                content = file_path.read_text(encoding="utf-8")
                summary = self._extract_summary_from_issue(content, issue_date)
                summaries.append(summary)
                log.debug("daily_summary_loaded", date=issue_date.isoformat())

        return sorted(summaries, key=lambda x: x["date"])

    def _extract_summary_from_issue(self, content: str, issue_date: date) -> dict[str, Any]:
        """Extract key information from a daily newsletter.

        Args:
            content: Full newsletter text content.
            issue_date: Date of the newsletter.

        Returns:
            Dictionary with date and extracted summary fields.
        """
        lines = content.split("\n")
        title = ""
        subtitle = ""
        opening = ""
        closing = ""

        for line in lines:
            if line.startswith("Title:"):
                title = line[6:].strip()
            elif line.startswith("Subtitle:"):
                subtitle = line[9:].strip()
            elif line.startswith("Opening Comment:"):
                opening = line[16:].strip()
            elif line.startswith("Closing Comment:"):
                closing = line[16:].strip()

        return {
            "date": issue_date.isoformat(),
            "title": title,
            "subtitle": subtitle,
            "opening": opening,
            "closing": closing,
        }

    def _build_prompt_data(
        self,
        daily_summaries: list[dict[str, Any]],
        narrative_context: NarrativeContext,
        reference_date: date,
    ) -> dict[str, Any]:
        """Build the prompt data for weekly digest generation.

        Args:
            daily_summaries: List of daily newsletter summaries.
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
