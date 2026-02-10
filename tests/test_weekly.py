# ABOUTME: Tests for weekly digest generator.
# ABOUTME: Validates weekly summary generation from daily bulletins.

from datetime import date
from types import SimpleNamespace
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
def weekly_settings(tmp_path) -> Settings:
    """Create settings for weekly testing."""
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
        previous_issues_dir=tmp_path / "previous_issues",
        templates_dir=tmp_path / "templates",
        data_dir=tmp_path / "data",
        weekly_lookback_days=7,
    )


@pytest.fixture
def sample_bulletins() -> list:
    """Create sample bulletin objects (SimpleNamespace mimicking ORM)."""
    return [
        SimpleNamespace(
            issue_date=date(2026, 2, 8),
            title="Titolo Sabato",
            subtitle="Sottotitolo sabato",
            content="Editoriale del sabato con analisi.",
            press_review=[
                {"category": "Giustizia", "comment": "Commento giustizia."},
                {"category": "Carceri", "comment": "Commento carceri."},
            ],
        ),
        SimpleNamespace(
            issue_date=date(2026, 2, 7),
            title="Titolo Venerdì",
            subtitle="Sottotitolo venerdì",
            content="Editoriale del venerdì.",
            press_review=[
                {"category": "Riforme", "comment": "Commento riforme."},
            ],
        ),
        SimpleNamespace(
            issue_date=date(2026, 2, 6),
            title="Titolo Giovedì",
            subtitle=None,
            content="Editoriale giovedì.",
            press_review=None,
        ),
    ]


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

    def test_build_summaries_from_bulletins(
        self,
        weekly_settings: Settings,
        sample_bulletins: list,
    ) -> None:
        """_build_summaries_from_bulletins extracts and sorts by date."""
        generator = WeeklyDigestGenerator(weekly_settings)
        summaries = generator._build_summaries_from_bulletins(sample_bulletins)

        assert len(summaries) == 3
        # Sorted ascending by date
        assert summaries[0]["date"] == "2026-02-06"
        assert summaries[1]["date"] == "2026-02-07"
        assert summaries[2]["date"] == "2026-02-08"

    def test_build_summaries_maps_fields(
        self,
        weekly_settings: Settings,
        sample_bulletins: list,
    ) -> None:
        """_build_summaries_from_bulletins maps all bulletin fields correctly."""
        generator = WeeklyDigestGenerator(weekly_settings)
        summaries = generator._build_summaries_from_bulletins(sample_bulletins)

        saturday = summaries[2]  # Feb 8
        assert saturday["title"] == "Titolo Sabato"
        assert saturday["subtitle"] == "Sottotitolo sabato"
        assert saturday["editorial"] == "Editoriale del sabato con analisi."
        assert len(saturday["press_review"]) == 2
        assert saturday["press_review"][0]["category"] == "Giustizia"

    def test_build_summaries_handles_null_fields(
        self,
        weekly_settings: Settings,
        sample_bulletins: list,
    ) -> None:
        """_build_summaries_from_bulletins handles None subtitle and press_review."""
        generator = WeeklyDigestGenerator(weekly_settings)
        summaries = generator._build_summaries_from_bulletins(sample_bulletins)

        thursday = summaries[0]  # Feb 6
        assert thursday["subtitle"] == ""
        assert thursday["press_review"] == []

    def test_build_prompt_data(
        self,
        weekly_settings: Settings,
        sample_narrative_context: NarrativeContext,
    ) -> None:
        """_build_prompt_data formats data correctly."""
        generator = WeeklyDigestGenerator(weekly_settings)

        daily_summaries = [
            {
                "date": "2026-02-08",
                "title": "Test",
                "subtitle": "",
                "editorial": "Editorial text",
                "press_review": [{"category": "Cat", "comment": "Comment"}],
            }
        ]

        prompt_data = generator._build_prompt_data(
            daily_summaries,
            sample_narrative_context,
            date(2026, 2, 8),
        )

        assert "daily_summaries" in prompt_data
        assert len(prompt_data["daily_summaries"]) == 1
        assert prompt_data["daily_summaries"][0]["editorial"] == "Editorial text"
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
        sample_bulletins: list,
        sample_narrative_context: NarrativeContext,
    ) -> None:
        """generate creates weekly digest content from bulletins."""
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

        generator = WeeklyDigestGenerator(weekly_settings)
        content = generator.generate(
            bulletins=sample_bulletins,
            reference_date=date(2026, 2, 8),
        )

        assert content.weekly_title == "Weekly Test Title"
        assert len(content.narrative_arcs) == 1

    def test_generate_raises_when_no_bulletins(
        self,
        weekly_settings: Settings,
    ) -> None:
        """generate raises ValueError when no bulletins provided."""
        with patch("behind_bars_pulse.newsletter.weekly.NarrativeStorage"):
            generator = WeeklyDigestGenerator(weekly_settings)

            with pytest.raises(ValueError, match="No bulletins found"):
                generator.generate(bulletins=[], reference_date=date(2026, 2, 8))

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
