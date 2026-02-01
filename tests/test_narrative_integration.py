# ABOUTME: Tests for narrative context integration in newsletter generation.
# ABOUTME: Validates that narrative context flows through to content generation.

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from behind_bars_pulse.ai.service import AIService
from behind_bars_pulse.config import Settings
from behind_bars_pulse.models import EnrichedArticle, NewsletterContent
from behind_bars_pulse.narrative.models import (
    CharacterPosition,
    FollowUp,
    KeyCharacter,
    NarrativeContext,
    StoryThread,
)
from behind_bars_pulse.newsletter.generator import NewsletterGenerator


@pytest.fixture
def integration_settings(tmp_path: Path) -> Settings:
    """Create settings for integration testing."""
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
        templates_dir=Path("src/behind_bars_pulse/email/templates"),
        data_dir=tmp_path / "data",
    )


@pytest.fixture
def sample_narrative_context() -> NarrativeContext:
    """Create a sample narrative context for testing."""
    return NarrativeContext(
        ongoing_storylines=[
            StoryThread(
                id="story-001",
                topic="Decreto Carceri",
                status="active",
                first_seen=date(2025, 1, 1),
                last_update=date(2025, 1, 10),
                summary="Il decreto carceri prosegue il suo iter parlamentare.",
                keywords=["decreto", "carceri", "riforma"],
                mention_count=5,
                impact_score=0.8,
            ),
        ],
        key_characters=[
            KeyCharacter(
                name="Carlo Nordio",
                role="Ministro della Giustizia",
                aliases=["Ministro Nordio"],
                positions=[
                    CharacterPosition(
                        date=date(2025, 1, 8),
                        stance="Il decreto è sufficiente per affrontare l'emergenza.",
                    ),
                ],
            ),
        ],
        pending_followups=[
            FollowUp(
                id="fu-001",
                event="Voto finale Senato sul Decreto Carceri",
                expected_date=date(2025, 2, 1),
                story_id="story-001",
                created_at=date(2025, 1, 10),
            ),
        ],
    )


@pytest.fixture
def sample_enriched_articles() -> dict[str, EnrichedArticle]:
    """Create sample enriched articles."""
    return {
        "https://example.com/1": EnrichedArticle(
            title="Nuovi sviluppi sul Decreto Carceri",
            link="https://example.com/1",
            content="Il Ministro Nordio ha annunciato modifiche...",
            author="Test Author",
            source="Test Source",
            summary="Sviluppi sul decreto carceri.",
        ),
    }


class TestAIServiceNarrativeContext:
    """Tests for AI service narrative context formatting."""

    def test_format_narrative_context_with_stories(
        self,
        integration_settings: Settings,
        sample_narrative_context: NarrativeContext,
    ) -> None:
        """Narrative context is formatted with active stories."""
        service = AIService(integration_settings)
        formatted = service._format_narrative_context(sample_narrative_context)

        assert "CONTESTO NARRATIVO" in formatted
        assert "Decreto Carceri" in formatted
        assert "Menzioni: 5" in formatted

    def test_format_narrative_context_with_characters(
        self,
        integration_settings: Settings,
        sample_narrative_context: NarrativeContext,
    ) -> None:
        """Narrative context includes key characters."""
        service = AIService(integration_settings)
        formatted = service._format_narrative_context(sample_narrative_context)

        assert "Carlo Nordio" in formatted
        assert "Ministro della Giustizia" in formatted
        assert "decreto è sufficiente" in formatted

    def test_format_narrative_context_with_followups(
        self,
        integration_settings: Settings,
        sample_narrative_context: NarrativeContext,
    ) -> None:
        """Narrative context includes pending followups."""
        service = AIService(integration_settings)
        formatted = service._format_narrative_context(sample_narrative_context)

        assert "Voto finale Senato" in formatted
        assert "2025-02-01" in formatted

    def test_format_narrative_context_empty(
        self,
        integration_settings: Settings,
    ) -> None:
        """Empty narrative context returns empty string."""
        service = AIService(integration_settings)
        formatted = service._format_narrative_context(NarrativeContext())

        # Still has section headers
        assert "CONTESTO NARRATIVO" in formatted

    def test_format_narrative_context_invalid_type(
        self,
        integration_settings: Settings,
    ) -> None:
        """Invalid context type returns empty string."""
        service = AIService(integration_settings)
        formatted = service._format_narrative_context("not a context")

        assert formatted == ""

    @patch.object(AIService, "_generate")
    def test_generate_newsletter_content_with_narrative(
        self,
        mock_generate: MagicMock,
        integration_settings: Settings,
        sample_enriched_articles: dict[str, EnrichedArticle],
        sample_narrative_context: NarrativeContext,
    ) -> None:
        """Newsletter content generation includes narrative context."""
        mock_generate.return_value = """{
            "title": "Test Title",
            "subtitle": "Test Subtitle",
            "opening": "Test opening with narrative references.",
            "closing": "Test closing."
        }"""

        service = AIService(integration_settings)
        result = service.generate_newsletter_content(
            sample_enriched_articles,
            [],
            narrative_context=sample_narrative_context,
        )

        assert isinstance(result, NewsletterContent)
        # Verify the prompt included narrative context
        call_args = mock_generate.call_args
        prompt = call_args.kwargs.get("prompt") or call_args.args[0]
        assert "CONTESTO NARRATIVO" in prompt
        assert "Decreto Carceri" in prompt


class TestNewsletterGeneratorNarrativeIntegration:
    """Tests for newsletter generator narrative integration."""

    @patch("behind_bars_pulse.newsletter.generator.AIService")
    @patch("behind_bars_pulse.newsletter.generator.FeedFetcher")
    @patch("behind_bars_pulse.newsletter.generator.NarrativeStorage")
    def test_generate_loads_narrative_context(
        self,
        mock_storage_class: MagicMock,
        mock_fetcher_class: MagicMock,
        mock_ai_class: MagicMock,
        integration_settings: Settings,
        sample_narrative_context: NarrativeContext,
        sample_enriched_articles: dict[str, EnrichedArticle],
    ) -> None:
        """Generator loads and uses narrative context."""
        from behind_bars_pulse.models import Article

        # Setup mocks
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_feed.return_value = {
            "https://example.com/1": Article(
                title="Test",
                link="https://example.com/1",
                content="Content",
            )
        }
        mock_fetcher_class.return_value = mock_fetcher

        mock_ai = MagicMock()
        mock_ai.enrich_articles.return_value = sample_enriched_articles
        mock_ai.generate_newsletter_content.return_value = NewsletterContent(
            title="Test",
            subtitle="Test",
            opening="Test",
            closing="Test",
        )
        mock_ai.review_newsletter_content.return_value = NewsletterContent(
            title="Test",
            subtitle="Test",
            opening="Test",
            closing="Test",
        )
        mock_ai.generate_press_review.return_value = []
        mock_ai_class.return_value = mock_ai

        mock_storage = MagicMock()
        mock_storage.load_context.return_value = sample_narrative_context
        mock_storage_class.return_value = mock_storage

        generator = NewsletterGenerator(integration_settings)
        generator.generate()

        # Verify narrative context was passed to content generation
        mock_ai.generate_newsletter_content.assert_called_once()
        call_kwargs = mock_ai.generate_newsletter_content.call_args.kwargs
        assert "narrative_context" in call_kwargs
        assert call_kwargs["narrative_context"] == sample_narrative_context

    @patch("behind_bars_pulse.newsletter.generator.AIService")
    @patch("behind_bars_pulse.newsletter.generator.FeedFetcher")
    @patch("behind_bars_pulse.newsletter.generator.NarrativeStorage")
    def test_generate_works_without_narrative_context(
        self,
        mock_storage_class: MagicMock,
        mock_fetcher_class: MagicMock,
        mock_ai_class: MagicMock,
        integration_settings: Settings,
        sample_enriched_articles: dict[str, EnrichedArticle],
    ) -> None:
        """Generator works when narrative context is empty."""
        from behind_bars_pulse.models import Article

        # Setup mocks
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_feed.return_value = {
            "https://example.com/1": Article(
                title="Test",
                link="https://example.com/1",
                content="Content",
            )
        }
        mock_fetcher_class.return_value = mock_fetcher

        mock_ai = MagicMock()
        mock_ai.enrich_articles.return_value = sample_enriched_articles
        mock_ai.generate_newsletter_content.return_value = NewsletterContent(
            title="Test",
            subtitle="Test",
            opening="Test",
            closing="Test",
        )
        mock_ai.review_newsletter_content.return_value = NewsletterContent(
            title="Test",
            subtitle="Test",
            opening="Test",
            closing="Test",
        )
        mock_ai.generate_press_review.return_value = []
        mock_ai_class.return_value = mock_ai

        mock_storage = MagicMock()
        mock_storage.load_context.return_value = NarrativeContext()  # Empty context
        mock_storage_class.return_value = mock_storage

        generator = NewsletterGenerator(integration_settings)
        content, press_review, articles = generator.generate()

        # Should complete without errors
        assert content is not None
        assert "narrative_context" in mock_ai.generate_newsletter_content.call_args.kwargs

    def test_load_narrative_context_returns_none_when_empty(
        self,
        integration_settings: Settings,
    ) -> None:
        """load_narrative_context returns None for empty context."""
        with patch("behind_bars_pulse.newsletter.generator.NarrativeStorage") as mock_storage_class:
            mock_storage = MagicMock()
            mock_storage.load_context.return_value = NarrativeContext()
            mock_storage_class.return_value = mock_storage

            generator = NewsletterGenerator(integration_settings)
            result = generator.load_narrative_context()

            assert result is None

    def test_load_narrative_context_returns_context_when_populated(
        self,
        integration_settings: Settings,
        sample_narrative_context: NarrativeContext,
    ) -> None:
        """load_narrative_context returns context when populated."""
        with patch("behind_bars_pulse.newsletter.generator.NarrativeStorage") as mock_storage_class:
            mock_storage = MagicMock()
            mock_storage.load_context.return_value = sample_narrative_context
            mock_storage_class.return_value = mock_storage

            generator = NewsletterGenerator(integration_settings)
            result = generator.load_narrative_context()

            assert result is not None
            assert len(result.ongoing_storylines) == 1
