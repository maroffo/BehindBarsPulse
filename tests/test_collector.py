# ABOUTME: Tests for ArticleCollector.
# ABOUTME: Validates daily collection pipeline with mocked dependencies.

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from behind_bars_pulse.collector import ArticleCollector
from behind_bars_pulse.config import Settings
from behind_bars_pulse.models import Article, EnrichedArticle


@pytest.fixture
def collector_settings(tmp_path: Path) -> Settings:
    """Create settings for collector testing."""
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
def mock_articles() -> dict[str, Article]:
    """Create mock articles returned by fetcher."""
    return {
        "https://example.com/1": Article(
            title="Test Article 1",
            link="https://example.com/1",
            content="Content about prison reform.",
        ),
        "https://example.com/2": Article(
            title="Test Article 2",
            link="https://example.com/2",
            content="Content about justice system.",
        ),
    }


@pytest.fixture
def mock_enriched_articles() -> dict[str, EnrichedArticle]:
    """Create mock enriched articles."""
    return {
        "https://example.com/1": EnrichedArticle(
            title="Test Article 1",
            link="https://example.com/1",
            content="Content about prison reform.",
            author="Author 1",
            source="Source 1",
            summary="Summary of article 1.",
        ),
        "https://example.com/2": EnrichedArticle(
            title="Test Article 2",
            link="https://example.com/2",
            content="Content about justice system.",
            author="Author 2",
            source="Source 2",
            summary="Summary of article 2.",
        ),
    }


class TestArticleCollector:
    """Tests for ArticleCollector."""

    def test_context_manager(self, collector_settings: Settings) -> None:
        """Collector can be used as context manager."""
        with patch.object(ArticleCollector, "close") as mock_close:
            with ArticleCollector(collector_settings):
                pass
            mock_close.assert_called_once()

    @patch("behind_bars_pulse.collector.AIService")
    @patch("behind_bars_pulse.collector.FeedFetcher")
    def test_collect_fetches_and_enriches(
        self,
        mock_fetcher_class: MagicMock,
        mock_ai_class: MagicMock,
        collector_settings: Settings,
        mock_articles: dict[str, Article],
        mock_enriched_articles: dict[str, EnrichedArticle],
    ) -> None:
        """Collect fetches RSS and enriches articles."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_feed.return_value = mock_articles
        mock_fetcher_class.return_value = mock_fetcher

        mock_ai = MagicMock()
        mock_ai.enrich_articles.return_value = mock_enriched_articles
        mock_ai_class.return_value = mock_ai

        collector = ArticleCollector(collector_settings)
        result = collector.collect(date(2025, 1, 15))

        mock_fetcher.fetch_feed.assert_called_once()
        mock_ai.enrich_articles.assert_called_once_with(mock_articles)
        assert len(result) == 2

    @patch("behind_bars_pulse.collector.AIService")
    @patch("behind_bars_pulse.collector.FeedFetcher")
    def test_collect_saves_to_storage(
        self,
        mock_fetcher_class: MagicMock,
        mock_ai_class: MagicMock,
        collector_settings: Settings,
        mock_articles: dict[str, Article],
        mock_enriched_articles: dict[str, EnrichedArticle],
    ) -> None:
        """Collect saves enriched articles to dated file."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_feed.return_value = mock_articles
        mock_fetcher_class.return_value = mock_fetcher

        mock_ai = MagicMock()
        mock_ai.enrich_articles.return_value = mock_enriched_articles
        mock_ai_class.return_value = mock_ai

        collector = ArticleCollector(collector_settings)
        collector.collect(date(2025, 1, 15))

        expected_file = collector_settings.data_dir / "collected_articles" / "2025-01-15.json"
        assert expected_file.exists()

    @patch("behind_bars_pulse.collector.AIService")
    @patch("behind_bars_pulse.collector.FeedFetcher")
    def test_collect_returns_empty_when_no_articles(
        self,
        mock_fetcher_class: MagicMock,
        mock_ai_class: MagicMock,
        collector_settings: Settings,
    ) -> None:
        """Collect returns empty dict when no articles fetched."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_feed.return_value = {}
        mock_fetcher_class.return_value = mock_fetcher

        mock_ai_class.return_value = MagicMock()

        collector = ArticleCollector(collector_settings)
        result = collector.collect()

        assert result == {}

    @patch("behind_bars_pulse.collector.AIService")
    @patch("behind_bars_pulse.collector.FeedFetcher")
    def test_collect_defaults_to_today(
        self,
        mock_fetcher_class: MagicMock,
        mock_ai_class: MagicMock,
        collector_settings: Settings,
        mock_articles: dict[str, Article],
        mock_enriched_articles: dict[str, EnrichedArticle],
    ) -> None:
        """Collect uses today's date by default."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_feed.return_value = mock_articles
        mock_fetcher_class.return_value = mock_fetcher

        mock_ai = MagicMock()
        mock_ai.enrich_articles.return_value = mock_enriched_articles
        mock_ai_class.return_value = mock_ai

        collector = ArticleCollector(collector_settings)
        collector.collect()

        expected_file = (
            collector_settings.data_dir / "collected_articles" / f"{date.today().isoformat()}.json"
        )
        assert expected_file.exists()
