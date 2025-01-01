from rssence.ai_helper import generate_summary
import rssence.feeds

import logging

log = logging.getLogger(__name__)


def fetch_feed_content(feed_url: str, number_of_items: int = 10) -> list:
    return rssence.feeds.fetch_feed_content(feed_url, number_of_items)


def enrich_content(feed_content: list[dict]) -> list[dict]:
    return rssence.feeds.enrich_content(feed_content)


def get_feed_summary(articles: list) -> str:
    feed_content = ""
    for article in articles:
        feed_content += f"Titolo: {article.get('title')}\n"
        feed_content += f"Link: {article.get('link')}\n"
        feed_content += f"Autore: {article.get('content')}\n"
        feed_content += f"Fonte: {article.get('source')}\n"
        feed_content += f"\n{article.get('content')}\n\n"
        feed_content += "---------------------------\n"

    newsletter_content = generate_summary(feed_content)
    return newsletter_content
