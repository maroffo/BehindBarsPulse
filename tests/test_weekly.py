# ABOUTME: Tests for weekly digest generator.
# ABOUTME: Validates weekly summary generation from daily newsletters.

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from behind_bars_pulse.config import Settings
from behind_bars_pulse.narrative.models import (
    FollowUp,
    KeyCharacter,
    NarrativeContext,
    StoryThread,
)
from behind_bars_pulse.newsletter.weekly import WeeklyDigestContent, WeeklyDigestGenerator


@pytest.fixture
def weekly_settings(tmp_path: Path) -> Settings:
    """Create settings for weekly testing."""
    # Create previous_issues directory
    issues_dir = tmp_path / "previous_issues"
    issues_dir.mkdir()

    return Settings(
        gemini_api_key=SecretStr("test-api-key"),
        gemini_model="gemini-test",
        gemini_fallback_model="gemini-fallback",
        ai_sleep_between_calls=0,
        feed_url="https://example.com/feed.rss",
        feed_timeout=5,
        max_articles=10,
        smtp_host="localhost",
        smtp_port=1025,
        ses_usr=SecretStr("test-user"),
        ses_pwd=SecretStr("test-password"),
        sender_email="test@example.com",
        sender_name="Test Sender",
        bounce_email="bounce@example.com",
        default_recipient="recipient@example.com",
        previous_issues_dir=issues_dir,
        templates_dir=Path("src/behind_bars_pulse/email/templates"),
        data_dir=tmp_path / "data",
        weekly_lookback_days=7,
    )


@pytest.fixture
def sample_issue_content() -> str:
    """Create sample newsletter content."""
    return """⚖️⛓️BehindBars - Notizie dal mondo della giustizia e delle carceri italiane - 15.01.2025
Title: Test Title for Newsletter
Subtitle: Test Subtitle explaining the day's themes
Opening Comment: This is the opening commentary with key insights.
Closing Comment: This is the closing reflection on the day's news.

Items:
Topic: Test Category
Test comment about the category.
1. Test Article - https://example.com/1
"""


@pytest.fixture
def sample_narrative_context() -> NarrativeContext:
    """Create sample narrative context."""
    return NarrativeContext(
        ongoing_storylines=[
            StoryThread(
                id="story-001",
                topic="Decreto Carceri",
                status="active",
                first_seen=date(2025, 1, 1),
                last_update=date(2025, 1, 15),
                summary="Ongoing legislative reform.",
                keywords=["decreto", "carceri"],
                mention_count=5,
                impact_score=0.8,
            ),
        ],
        key_characters=[
            KeyCharacter(
                name="Carlo Nordio",
                role="Ministro della Giustizia",
            ),
        ],
        pending_followups=[
            FollowUp(
                id="fu-001",
                event="Voto Senato",
                expected_date=date(2025, 2, 1),
                created_at=date(2025, 1, 10),
            ),
        ],
    )


class TestWeeklyDigestContent:
    """Tests for WeeklyDigestContent."""

    def test_create_content(self) -> None:
        """WeeklyDigestContent can be created."""
        content = WeeklyDigestContent(
            weekly_title="Test Weekly Title",
            weekly_subtitle="Test Subtitle",
            narrative_arcs=[{"arc_title": "Test Arc", "summary": "Test summary"}],
            weekly_reflection="Test reflection text.",
            upcoming_events=[{"event": "Test Event", "date": "2025-02-01"}],
        )

        assert content.weekly_title == "Test Weekly Title"
        assert len(content.narrative_arcs) == 1
        assert len(content.upcoming_events) == 1


class TestWeeklyDigestGenerator:
    """Tests for WeeklyDigestGenerator."""

    def test_extract_summary_from_issue(
        self,
        weekly_settings: Settings,
        sample_issue_content: str,
    ) -> None:
        """_extract_summary_from_issue extracts key fields."""
        generator = WeeklyDigestGenerator(weekly_settings)
        summary = generator._extract_summary_from_issue(sample_issue_content, date(2025, 1, 15))

        assert summary["date"] == "2025-01-15"
        assert summary["title"] == "Test Title for Newsletter"
        assert "Subtitle" in summary["subtitle"]
        assert "opening" in summary["opening"].lower()
        assert "closing" in summary["closing"].lower()

    def test_load_daily_summaries(
        self,
        weekly_settings: Settings,
        sample_issue_content: str,
    ) -> None:
        """_load_daily_summaries loads existing issues."""
        # Create some test issue files
        issues_dir = Path(weekly_settings.previous_issues_dir)
        reference_date = date(2025, 1, 15)

        for i in range(3):
            issue_date = reference_date - timedelta(days=i)
            file_name = f"{issue_date.strftime('%Y%m%d')}_issue.txt"
            (issues_dir / file_name).write_text(sample_issue_content)

        generator = WeeklyDigestGenerator(weekly_settings)
        summaries = generator._load_daily_summaries(reference_date, 7)

        assert len(summaries) == 3
        # Should be sorted oldest first
        assert summaries[0]["date"] == "2025-01-13"

    def test_load_daily_summaries_empty_dir(self, weekly_settings: Settings) -> None:
        """_load_daily_summaries returns empty list when no issues exist."""
        generator = WeeklyDigestGenerator(weekly_settings)
        summaries = generator._load_daily_summaries(date(2025, 1, 15), 7)

        assert summaries == []

    def test_build_prompt_data(
        self,
        weekly_settings: Settings,
        sample_narrative_context: NarrativeContext,
    ) -> None:
        """_build_prompt_data formats data correctly."""
        generator = WeeklyDigestGenerator(weekly_settings)

        daily_summaries = [
            {"date": "2025-01-15", "title": "Test", "opening": "Test", "closing": "Test"}
        ]

        prompt_data = generator._build_prompt_data(
            daily_summaries,
            sample_narrative_context,
            date(2025, 1, 15),
        )

        assert "daily_summaries" in prompt_data
        assert len(prompt_data["daily_summaries"]) == 1
        assert "narrative_context" in prompt_data
        assert len(prompt_data["narrative_context"]["top_stories"]) == 1
        assert prompt_data["narrative_context"]["top_stories"][0]["topic"] == "Decreto Carceri"

    @patch("behind_bars_pulse.newsletter.weekly.NarrativeStorage")
    @patch("behind_bars_pulse.newsletter.weekly.AIService")
    def test_generate_creates_digest(
        self,
        mock_ai_class: MagicMock,
        mock_storage_class: MagicMock,
        weekly_settings: Settings,
        sample_issue_content: str,
        sample_narrative_context: NarrativeContext,
    ) -> None:
        """generate creates weekly digest content."""
        # Setup mock AI
        mock_ai = MagicMock()
        mock_ai._generate.return_value = """{
            "weekly_title": "Weekly Test Title",
            "weekly_subtitle": "Weekly Subtitle",
            "narrative_arcs": [
                {"arc_title": "Test Arc", "summary": "Arc summary"}
            ],
            "weekly_reflection": "Weekly reflection text.",
            "upcoming_events": []
        }"""
        mock_ai_class.return_value = mock_ai

        # Setup mock storage
        mock_storage = MagicMock()
        mock_storage.load_context.return_value = sample_narrative_context
        mock_storage_class.return_value = mock_storage

        # Create test issues
        issues_dir = Path(weekly_settings.previous_issues_dir)
        reference_date = date(2025, 1, 15)
        for i in range(3):
            issue_date = reference_date - timedelta(days=i)
            file_name = f"{issue_date.strftime('%Y%m%d')}_issue.txt"
            (issues_dir / file_name).write_text(sample_issue_content)

        generator = WeeklyDigestGenerator(weekly_settings)
        content = generator.generate(reference_date=reference_date)

        assert content.weekly_title == "Weekly Test Title"
        assert len(content.narrative_arcs) == 1

    def test_generate_raises_when_no_dailies(
        self,
        weekly_settings: Settings,
        sample_narrative_context: NarrativeContext,
    ) -> None:
        """generate raises ValueError when no daily newsletters found."""
        with patch("behind_bars_pulse.newsletter.weekly.NarrativeStorage") as mock_storage_class:
            mock_storage = MagicMock()
            mock_storage.load_context.return_value = sample_narrative_context
            mock_storage_class.return_value = mock_storage

            generator = WeeklyDigestGenerator(weekly_settings)

            with pytest.raises(ValueError, match="No daily newsletters"):
                generator.generate(reference_date=date(2025, 1, 15))

    def test_build_context(
        self,
        weekly_settings: Settings,
    ) -> None:
        """build_context creates NewsletterContext for email."""
        generator = WeeklyDigestGenerator(weekly_settings)

        content = WeeklyDigestContent(
            weekly_title="Weekly Title",
            weekly_subtitle="Weekly Subtitle",
            narrative_arcs=[{"arc_title": "Test Arc", "summary": "Arc summary text here."}],
            weekly_reflection="Reflection on the week.",
            upcoming_events=[
                {"event": "Test Event", "date": "2025-02-01", "significance": "Important"}
            ],
        )

        context = generator.build_context(
            content,
            week_start=date(2025, 1, 9),
            week_end=date(2025, 1, 15),
        )

        assert "Digest Settimanale" in context.subject
        assert "09.01 - 15.01.2025" in context.subject
        assert context.newsletter_title == "Weekly Title"
        assert "Test Arc" in context.newsletter_opening
        assert "Reflection" in context.newsletter_closing
        assert "Test Event" in context.newsletter_closing
