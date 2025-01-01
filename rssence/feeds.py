import json
from typing import Optional

import feedparser
import requests
from readability import Document
from bs4 import BeautifulSoup

from .ai_helper import extract_infos


def fetch_feed_content(feed_url: str, number_of_items: int = 10) -> list:
    """
    Downloads and parses an RSS feed.
    """
    feed = feedparser.parse(feed_url,
                            agent=("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                   "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 "
                                   "Safari/605.1.15"))

    if feed.bozo:  # Verifica errori nel parsing
        print(f"Error parsing feed: {feed.bozo_exception}")
        return None

    articles = []

    for entry in feed.entries[:number_of_items]:
        content = fetch_article_content(entry.link)
        if content:
            articles.append({
                "title": entry.title,
                "link": entry.link,
                "content": content,
            })
    return articles


def summarize_and_extract_infos(content) -> dict:
    infos = json.loads(extract_infos(content))
    return infos


def enrich_content(feed_content: list[dict]) -> list[dict]:
    new_feed_content = []
    for article in feed_content:
        extra_info = summarize_and_extract_infos(article["content"])
        article['author'] = extra_info[0]['author']
        article['source'] = extra_info[0]['source']
        article['summary'] = extra_info[0]['summary']
        new_feed_content.append(article)
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
