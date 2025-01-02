import json
from typing import Optional

from rssence.ai_helper import generate_opening_message, generate_closing_message, generate_newsletter_content, \
    generate_press_review
import rssence.feeds

import logging

log = logging.getLogger(__name__)


def fetch_feed_content(feed_url: str, number_of_items: int = 10) -> Optional[dict]:
    return rssence.feeds.fetch_feed_content(feed_url, number_of_items)


def enrich_content(feed_content: dict) -> dict:
    return rssence.feeds.enrich_content(feed_content)


def get_press_review(feed_articles: dict) -> list:
    log.debug("Generate newsletter content")
    temporary_review = json.loads(generate_press_review(feed_articles))
    press_review = []
    for item in temporary_review:
        topic = {'category': item['category'], 'comment': item['comment']}
        articles = []
        for article in item['articles']:
            article['author'] = feed_articles.get(article['link']).get('author', '')
            article['source'] = feed_articles.get(article['link']).get('source', '')
            if article['importance'] == 'Alta':
                article['summary'] = feed_articles.get(article['link']).get('summary', '')
            else:
                article['summary'] = None
            articles.append(article)
        topic['articles'] = articles
        press_review.append(topic)
    return press_review


def get_newsletter_content(articles: dict) -> dict:
    log.debug("Generate newsletter content")
    feed_content = aggregate_articles_content(articles)
    newsletter_content = generate_newsletter_content(feed_content)
    return json.loads(newsletter_content)


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


def articles_to_json(articles) -> str:
    return json.dumps(articles, indent=2)


def aggregate_articles_content(articles: dict) -> str:
    feed_content = ""
    for article_key in articles:
        article = articles[article_key]
        feed_content += f"Titolo: {article.get('title')}\n"
        feed_content += f"Link: {article.get('link')}\n"
        feed_content += f"Autore: {article.get('author')}\n"
        feed_content += f"Fonte: {article.get('source')}\n"
        feed_content += f"Contenuto: ```{article.get('content')}```\n"
        feed_content += "---\n"
    return feed_content
