# ABOUTME: Tests for newsletter generation and orchestration.
# ABOUTME: Verifies NewsletterGenerator pipeline and context building.

from pathlib import Path

from behind_bars_pulse.config import Settings
from behind_bars_pulse.models import (
    EnrichedArticle,
    NewsletterContent,
    NewsletterContext,
    PressReviewCategory,
)
from behind_bars_pulse.newsletter.generator import NewsletterGenerator


class TestNewsletterGenerator:
    """Tests for NewsletterGenerator class."""

    def test_generator_initialization(self, mock_settings: Settings) -> None:
        """NewsletterGenerator should initialize with settings."""
        generator = NewsletterGenerator(mock_settings)
        assert generator.settings == mock_settings
        generator.close()

    def test_generator_context_manager(self, mock_settings: Settings) -> None:
        """NewsletterGenerator should work as context manager."""
        with NewsletterGenerator(mock_settings) as generator:
            assert generator is not None

    def test_read_previous_issues_empty_dir(self, mock_settings: Settings) -> None:
        """read_previous_issues should return empty list for missing dir."""
        with NewsletterGenerator(mock_settings) as generator:
            issues = generator.read_previous_issues()
        assert issues == []

    def test_read_previous_issues_with_files(
        self,
        mock_settings: Settings,
        tmp_path: Path,
    ) -> None:
        """read_previous_issues should read .txt files from directory."""
        issues_dir = tmp_path / "previous_issues"
        issues_dir.mkdir()
        (issues_dir / "20250101_issue.txt").write_text("Issue 1 content")
        (issues_dir / "20250102_issue.txt").write_text("Issue 2 content")
        (issues_dir / "ignored.html").write_text("Should be ignored")

        mock_settings.previous_issues_dir = issues_dir

        with NewsletterGenerator(mock_settings) as generator:
            issues = generator.read_previous_issues()

        assert len(issues) == 2
        assert "Issue 1 content" in issues
        assert "Issue 2 content" in issues

    def test_build_context(
        self,
        mock_settings: Settings,
        sample_newsletter_content: NewsletterContent,
        sample_press_review: list[PressReviewCategory],
    ) -> None:
        """build_context should create complete NewsletterContext."""
        with NewsletterGenerator(mock_settings) as generator:
            context = generator.build_context(
                sample_newsletter_content,
                sample_press_review,
                "28.01.2025",
            )

        assert isinstance(context, NewsletterContext)
        assert "28.01.2025" in context.subject
        assert context.newsletter_title == sample_newsletter_content.title
        assert context.press_review == sample_press_review

    def test_merge_enriched_data(
        self,
        mock_settings: Settings,
        sample_press_review: list[PressReviewCategory],
        sample_enriched_articles: dict[str, EnrichedArticle],
    ) -> None:
        """_merge_enriched_data should add author/source/summary to press review."""
        with NewsletterGenerator(mock_settings) as generator:
            merged = generator._merge_enriched_data(
                sample_press_review,
                sample_enriched_articles,
            )

        article = merged[0].articles[0]
        assert article.author == "Test Author"
        assert article.source == "Test Source"
        assert article.summary == "This is a summary of the test article."


class TestNewsletterContent:
    """Tests for NewsletterContent model."""

    def test_newsletter_content_creation(self) -> None:
        """NewsletterContent should be created with all fields."""
        content = NewsletterContent(
            title="Title",
            subtitle="Subtitle",
            opening="Opening",
            closing="Closing",
        )

        assert content.title == "Title"
        assert content.subtitle == "Subtitle"
        assert content.opening == "Opening"
        assert content.closing == "Closing"

    def test_newsletter_content_json_serialization(
        self,
        sample_newsletter_content: NewsletterContent,
    ) -> None:
        """NewsletterContent should serialize to JSON."""
        json_str = sample_newsletter_content.model_dump_json()
        assert "Test Newsletter Title" in json_str
        assert "Test Newsletter Subtitle" in json_str


class TestNewsletterContext:
    """Tests for NewsletterContext model."""

    def test_newsletter_context_defaults(self) -> None:
        """NewsletterContext should have default empty notification list."""
        context = NewsletterContext(
            subject="Test Subject",
            today_str="28.01.2025",
            newsletter_title="Title",
            newsletter_subtitle="Subtitle",
            newsletter_opening="Opening",
            newsletter_closing="Closing",
            press_review=[],
        )

        assert context.notification_address_list == []

    def test_newsletter_context_with_recipients(self) -> None:
        """NewsletterContext should accept notification list."""
        context = NewsletterContext(
            subject="Test Subject",
            today_str="28.01.2025",
            newsletter_title="Title",
            newsletter_subtitle="Subtitle",
            newsletter_opening="Opening",
            newsletter_closing="Closing",
            press_review=[],
            notification_address_list=["test@example.com"],
        )

        assert len(context.notification_address_list) == 1
