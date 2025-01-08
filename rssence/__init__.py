import json
from typing import Optional

from rssence.ai_helper import generate_newsletter_content, generate_press_review, review_newsletter_content
import rssence.feeds

import logging

log = logging.getLogger(__name__)


def fetch_feed_content(feed_url: str, number_of_items: int = 10) -> Optional[dict]:
    return rssence.feeds.fetch_feed_content(feed_url, number_of_items)


def enrich_content(feed_content: dict) -> dict:
    return rssence.feeds.enrich_content(feed_content)


def get_press_review(feed_articles: dict) -> list:
    log.info("Generate press review")
    temporary_review = json.loads(generate_press_review(feed_articles))
    press_review = []
    for item in temporary_review:
        topic = {'category': item['category'], 'comment': item['comment']}
        articles = []
        for article in item['articles']:
            article['author'] = feed_articles.get(article['link']).get('author', '')
            article['source'] = feed_articles.get(article['link']).get('source', '')
            article['summary'] = feed_articles.get(article['link']).get('summary', '')
            articles.append(article)
        topic['articles'] = articles
        press_review.append(topic)
    return press_review


def get_newsletter_content(articles: dict, previous_issues: list) -> dict:
    log.info("Generate newsletter content")
    feed_content = aggregate_articles_content(articles)
    newsletter_content = review_newsletter_content(generate_newsletter_content(feed_content, previous_issues),
                                                   previous_issues)
    return json.loads(newsletter_content)


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
