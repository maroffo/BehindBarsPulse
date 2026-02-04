# ABOUTME: RSS feed fetcher and article content extractor.
# ABOUTME: Uses feedparser for RSS and httpx + readability for content extraction.

import contextlib
from datetime import UTC, date, datetime

import feedparser
import httpx
import structlog
from bs4 import BeautifulSoup
from readability import Document

from behind_bars_pulse.config import Settings, get_settings
from behind_bars_pulse.models import Article

log = structlog.get_logger()


class FeedFetcher:
    """Fetches and extracts content from RSS feeds."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client: httpx.Client | None = None

    @property
    def client(self) -> httpx.Client:
        """Lazy-initialized HTTP client."""
        if self._client is None:
            self._client = httpx.Client(
                timeout=self.settings.feed_timeout,
                headers={"User-Agent": self.settings.feed_user_agent},
                follow_redirects=True,
            )
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> "FeedFetcher":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def fetch_feed(self, max_articles: int | None = None) -> dict[str, Article]:
        """Fetch articles from the configured RSS feed.

        Args:
            max_articles: Maximum number of articles to fetch. Defaults to settings value.

        Returns:
            Dictionary mapping article URLs to Article objects.
        """
        max_articles = max_articles or self.settings.max_articles
        feed_url = self.settings.feed_url

        log.debug("fetching_feed", url=feed_url)

        today_midnight = datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")

        feed = feedparser.parse(
            feed_url,
            agent=self.settings.feed_user_agent,
            modified=today_midnight,
        )

        if feed.bozo:
            log.error("feed_parse_error", error=str(feed.bozo_exception))
            return {}

        articles: dict[str, Article] = {}

        for entry in feed.entries[:max_articles]:
            log.info("fetching_article", url=entry.link)
            content = self._fetch_article_content(entry.link)

            if content:
                # Extract publication date from RSS entry
                published_date = None
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    with contextlib.suppress(ValueError, TypeError):
                        published_date = date(*entry.published_parsed[:3])

                log.info("article_fetched", title=entry.title, published=published_date)
                articles[entry.link] = Article(
                    title=entry.title,
                    link=entry.link,
                    content=content,
                    published_date=published_date,
                )

        return articles

    def _fetch_article_content(self, url: str) -> str | None:
        """Download and extract the main content of an article.

        Args:
            url: The article URL to fetch.

        Returns:
            Extracted text content, or None if extraction failed.
        """
        try:
            response = self.client.get(url)
            response.raise_for_status()

            doc = Document(response.text)
            html_content = doc.summary()

            soup = BeautifulSoup(html_content, "html.parser")
            text_content = soup.get_text(separator="\n").strip()

            return text_content

        except httpx.HTTPError as e:
            log.error("article_fetch_error", url=url, error=str(e))
            return None
