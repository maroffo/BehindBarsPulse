import json
from time import sleep
from typing import Optional

from dateutil.utils import today

import feedparser
import requests
from readability import Document
from bs4 import BeautifulSoup

from .ai_helper import extract_infos

import logging

log = logging.getLogger(__name__)


def fetch_feed_content(feed_url: str, number_of_items: int = 10) -> Optional[dict]:
    """
    Downloads and parses an RSS feed.
    """

    logging.debug(f"Fetching feed from {feed_url}")

    today_midnight = today().strftime('%a, %d %b %Y %H:%M:%S GMT')
    # today_midnight = "Wed, 01 Jan 2025 00:00:00 GMT"

    feed = feedparser.parse(feed_url,
                            agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 "
                                   "Safari/605.1.15"),
                            modified=today_midnight)

    if feed.bozo:  # Verifica errori nel parsing
        log.error(f"Error parsing feed: {feed.bozo_exception}")
        return None

    articles = {}

    for entry in feed.entries[:number_of_items]:
        log.debug(f"Fetching article content from {entry.link}")
        content = fetch_article_content(entry.link)
        if content:
            log.debug(f"Fetched article {entry.title}")
            articles[entry.link] = {
                "title": entry.title,
                "link": entry.link,
                "content": content,
            }
    return articles


def summarize_and_extract_infos(content) -> dict:
    log.debug(f"Extracting infos from '{content[:15]}...'")
    infos = json.loads(extract_infos(content))
    return infos


def enrich_content(feed_content: dict) -> dict:
    log.debug(f"Enriching content of '{len(feed_content)}' articles'")
    new_feed_content = {}
    for content in feed_content:
        article = feed_content[content]
        extra_info = summarize_and_extract_infos(article["content"])
        article['author'] = extra_info[0]['author']
        article['source'] = extra_info[0]['source']
        article['summary'] = extra_info[0]['summary']
        new_feed_content[content] = article
    return new_feed_content


def fetch_article_content(article_url) -> Optional[str]:
    """
    Downloads and extracts the main content of a single article.
    """
    try:
        response = requests.get(article_url, timeout=10)
        response.raise_for_status()

        # Use python-readability to extract the main content
        doc = Document(response.text)
        html_content = doc.summary()  # Cleaned HTML of the main content

        # Use BeautifulSoup to extract readable text
        soup = BeautifulSoup(html_content, "html.parser")
        # .get_text(separator="\n") joins all text with newline characters
        # .strip() removes leading/trailing whitespace
        text_content = soup.get_text(separator="\n").strip()

        return text_content

    except requests.RequestException as e:
        print(f"Error downloading the article content: {e}")
        return None
