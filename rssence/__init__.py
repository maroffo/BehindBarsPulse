from rssence.ai_helper import generate_opening_message, generate_closing_message
import rssence.feeds

import logging

log = logging.getLogger(__name__)


def fetch_feed_content(feed_url: str, number_of_items: int = 10) -> list:
    return rssence.feeds.fetch_feed_content(feed_url, number_of_items)


def enrich_content(feed_content: list[dict]) -> list[dict]:
    return rssence.feeds.enrich_content(feed_content)


def get_newsletter_opening(articles: list) -> str:
    log.debug("Generate newsletter opening message")
    feed_content = aggregate_articles_content(articles)
    newsletter_opening = generate_opening_message(feed_content)
    return newsletter_opening


def get_newsletter_closing(newsletter_opening: str, articles: list) -> str:
    log.debug("Generate newsletter closing message")
    feed_content = aggregate_articles_content(articles)
    newsletter_content = newsletter_opening + '\n\n' + feed_content
    newsletter_closing = generate_closing_message(newsletter_content)
    return newsletter_closing


def aggregate_articles_content(articles):
    feed_content = ""
    for article in articles:
        feed_content += f"Titolo: {article.get('title')}\n"
        feed_content += f"Link: {article.get('link')}\n"
        feed_content += f"Autore: {article.get('content')}\n"
        feed_content += f"Fonte: {article.get('source')}\n"
        feed_content += f"\n{article.get('content')}\n\n"
        feed_content += "---------------------------\n"
    return feed_content
