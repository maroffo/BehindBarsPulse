# ABOUTME: Pytest fixtures and configuration for BehindBarsPulse tests.
# ABOUTME: Provides mock settings, sample data, and test utilities.

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from behind_bars_pulse.config import Settings
from behind_bars_pulse.models import (
    Article,
    EnrichedArticle,
    NewsletterContent,
    PressReviewArticle,
    PressReviewCategory,
)


@pytest.fixture
def mock_settings(tmp_path: Path) -> Settings:
    """Create mock settings for testing."""
    return Settings(
        gcp_project="test-project",
        gcp_location="global",
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
        log_level="DEBUG",
    )


@pytest.fixture
def sample_article() -> Article:
    """Create a sample Article for testing."""
    return Article(
        title="Test Article Title",
        link="https://example.com/article-1",
        content="This is the test article content about the Italian prison system.",
    )


@pytest.fixture
def sample_enriched_article() -> EnrichedArticle:
    """Create a sample EnrichedArticle for testing."""
    return EnrichedArticle(
        title="Test Article Title",
        link="https://example.com/article-1",
        content="This is the test article content about the Italian prison system.",
        author="Test Author",
        source="Test Source",
        summary="This is a summary of the test article.",
    )


@pytest.fixture
def sample_articles(sample_article: Article) -> dict[str, Article]:
    """Create a dictionary of sample articles."""
    return {str(sample_article.link): sample_article}


@pytest.fixture
def sample_enriched_articles(
    sample_enriched_article: EnrichedArticle,
) -> dict[str, EnrichedArticle]:
    """Create a dictionary of sample enriched articles."""
    return {str(sample_enriched_article.link): sample_enriched_article}


@pytest.fixture
def sample_newsletter_content() -> NewsletterContent:
    """Create sample newsletter content."""
    return NewsletterContent(
        title="Test Newsletter Title",
        subtitle="Test Newsletter Subtitle",
        opening="This is the opening commentary for the test newsletter.",
        closing="This is the closing commentary for the test newsletter.",
    )


@pytest.fixture
def sample_press_review() -> list[PressReviewCategory]:
    """Create sample press review categories."""
    return [
        PressReviewCategory(
            category="Test Category",
            comment="This is a test category comment.",
            articles=[
                PressReviewArticle(
                    title="Test Article Title",  # Must match sample_enriched_article
                    link="https://example.com/article-1",
                    importance="Alta",
                    author="",
                    source="",
                    summary="",
                ),
            ],
        ),
    ]


@pytest.fixture
def mock_genai_client() -> MagicMock:
    """Create a mock Google GenAI client."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.text = '{"test": "response"}'
    mock_client.models.generate_content_stream.return_value = [mock_response]
    return mock_client
