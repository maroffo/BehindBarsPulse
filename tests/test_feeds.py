# ABOUTME: Tests for RSS feed fetching and content extraction.
# ABOUTME: Verifies FeedFetcher behavior with mocked HTTP responses.

from unittest.mock import MagicMock, patch

import httpx

from behind_bars_pulse.config import Settings
from behind_bars_pulse.feeds.fetcher import FeedFetcher
from behind_bars_pulse.models import Article


class TestFeedFetcher:
    """Tests for FeedFetcher class."""

    def test_fetcher_initialization(self, mock_settings: Settings) -> None:
        """FeedFetcher should initialize with settings."""
        fetcher = FeedFetcher(mock_settings)
        assert fetcher.settings == mock_settings
        assert fetcher._client is None

    def test_fetcher_client_lazy_initialization(self, mock_settings: Settings) -> None:
        """HTTP client should be lazily initialized."""
        fetcher = FeedFetcher(mock_settings)
        assert fetcher._client is None

        client = fetcher.client
        assert client is not None
        assert fetcher._client is client

        # Same instance on second access
        assert fetcher.client is client

        fetcher.close()

    def test_fetcher_context_manager(self, mock_settings: Settings) -> None:
        """FeedFetcher should work as context manager."""
        with FeedFetcher(mock_settings) as fetcher:
            _ = fetcher.client
            assert fetcher._client is not None

        assert fetcher._client is None

    @patch("behind_bars_pulse.feeds.fetcher.feedparser.parse")
    def test_fetch_feed_empty_on_parse_error(
        self,
        mock_parse: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """fetch_feed should return empty dict on parse error."""
        mock_parse.return_value = MagicMock(bozo=True, bozo_exception="Parse error")

        with FeedFetcher(mock_settings) as fetcher:
            result = fetcher.fetch_feed()

        assert result == {}

    @patch("behind_bars_pulse.feeds.fetcher.feedparser.parse")
    def test_fetch_feed_respects_max_articles(
        self,
        mock_parse: MagicMock,
        mock_settings: Settings,
    ) -> None:
        """fetch_feed should respect max_articles limit."""
        entries = [
            MagicMock(link=f"https://example.com/{i}", title=f"Article {i}") for i in range(20)
        ]
        mock_parse.return_value = MagicMock(bozo=False, entries=entries)

        with (
            patch.object(FeedFetcher, "_fetch_article_content", return_value="content"),
            FeedFetcher(mock_settings) as fetcher,
        ):
            result = fetcher.fetch_feed(max_articles=5)

        assert len(result) == 5

    def test_fetch_article_content_handles_http_error(self, mock_settings: Settings) -> None:
        """_fetch_article_content should return None on HTTP error."""
        with FeedFetcher(mock_settings) as fetcher:
            fetcher.client.get = MagicMock(side_effect=httpx.HTTPError("Connection error"))
            result = fetcher._fetch_article_content("https://example.com/article")

        assert result is None


class TestArticleModel:
    """Tests for Article model."""

    def test_article_creation(self) -> None:
        """Article should be created with required fields."""
        article = Article(
            title="Test Title",
            link="https://example.com/test",
            content="Test content",
        )

        assert article.title == "Test Title"
        assert article.link == "https://example.com/test"
        assert article.content == "Test content"
