import json
import time

import feedparser
import requests
from readability import Document
from bs4 import BeautifulSoup

from .ai_helper import extract_infos


def fetch_feed(feed_url):
    """
    Scarica e analizza un feed RSS.
    """
    feed = feedparser.parse(feed_url,
                            agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15")

    if feed.bozo:  # Verifica errori nel parsing
        print(f"Errore nel parsing del feed: {feed.bozo_exception}")
        return None

    articles = []

    for entry in feed.entries[:9]:  # Limita a 2 articoli per esempio
        content = fetch_article_content(entry.link)
        if content:
            time.sleep(60)
            infos = json.loads(extract_infos(content))
            articles.append({
                "title": entry.title,
                "link": entry.link,
                "content": content,
                "author": infos[0]['author'],
                "source": infos[0]['source'],
                "summary": infos[0]['summary'],
            })
    return articles


def fetch_article_content(article_url) -> str:
    """
    Scarica e analizza il contenuto di un singolo articolo.
    """
    try:
        response = requests.get(article_url, timeout=10)
        response.raise_for_status()

        # Usa python-readability per estrarre il contenuto principale
        doc = Document(response.text)
        html_content = doc.summary()  # HTML pulito del contenuto principale

        # Usa BeautifulSoup per estrarre il testo leggibile
        soup = BeautifulSoup(html_content, "html.parser")
        text_content = soup.get_text(separator="\n").strip()

        return text_content

    except requests.RequestException as e:
        print(f"Errore durante il download dell'articolo: {e}")
        return None
