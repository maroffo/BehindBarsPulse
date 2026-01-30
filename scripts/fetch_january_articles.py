# ABOUTME: Script to fetch and process January 2026 articles from scraped URLs.
# ABOUTME: Uses readability for content extraction, saves as enriched articles.

import asyncio
import json
import re
from datetime import date
from pathlib import Path

import httpx
from bs4 import BeautifulSoup
from readability import Document

BASE_DIR = Path(__file__).parent.parent
URLS_FILE = BASE_DIR / "data" / "scraped_urls" / "january_2026_urls.json"
OUTPUT_FILE = BASE_DIR / "data" / "collected_articles" / "2026-01-january-backfill.json"

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

# Concurrent requests limit
MAX_CONCURRENT = 5
DELAY_BETWEEN_BATCHES = 1.0


async def fetch_article(client: httpx.AsyncClient, url: str) -> dict | None:
    """Fetch and parse a single article."""
    try:
        response = await client.get(url, timeout=30.0)
        response.raise_for_status()
        html = response.text

        # Use readability to extract main content
        doc = Document(html)
        title = doc.title()
        content_html = doc.summary()

        # Clean content to plain text
        soup = BeautifulSoup(content_html, "html.parser")
        content = soup.get_text(separator="\n", strip=True)

        # Try to extract author and source from content
        author = None
        source = None

        # Common patterns: "di Nome Cognome" at start, or "*Nome Cognome"
        author_match = re.search(r"(?:^|\n)\s*(?:di|Di|DI)\s+([A-Z][a-zà-ú]+(?:\s+[A-Z][a-zà-ú]+)+)", content)
        if author_match:
            author = author_match.group(1).strip()

        # Source often in bold or after author: "Il Fatto Quotidiano, 29 gennaio 2026"
        source_match = re.search(r"\n([A-Za-z\s\.]+(?:\.it|\.com|\.org)?),?\s*\d{1,2}\s+\w+\s+202\d", content)
        if source_match:
            source = source_match.group(1).strip()

        # Extract date from content if possible
        date_match = re.search(r"(\d{1,2})\s+(gennaio|febbraio|marzo|aprile|maggio|giugno|luglio|agosto|settembre|ottobre|novembre|dicembre)\s+(202\d)", content, re.IGNORECASE)
        pub_date = None
        if date_match:
            day = int(date_match.group(1))
            month_name = date_match.group(2).lower()
            year = int(date_match.group(3))
            months = {
                "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4,
                "maggio": 5, "giugno": 6, "luglio": 7, "agosto": 8,
                "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12
            }
            try:
                pub_date = date(year, months[month_name], day).isoformat()
            except ValueError:
                pass

        if not content or len(content) < 100:
            return None

        return {
            "title": title,
            "link": url,
            "content": content[:10000],  # Limit content size
            "author": author,
            "source": source or "Ristretti Orizzonti",
            "published_date": pub_date,
        }

    except Exception as e:
        print(f"  Error fetching {url}: {e}")
        return None


async def fetch_batch(client: httpx.AsyncClient, urls: list[str]) -> list[dict]:
    """Fetch a batch of articles concurrently."""
    tasks = [fetch_article(client, url) for url in urls]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r is not None]


async def main():
    # Load URLs
    with open(URLS_FILE) as f:
        data = json.load(f)
    urls = data["urls"]

    print(f"Loaded {len(urls)} URLs to fetch")
    print()

    all_articles = []

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    ) as client:
        # Process in batches
        for i in range(0, len(urls), MAX_CONCURRENT):
            batch = urls[i:i + MAX_CONCURRENT]
            print(f"Fetching batch {i // MAX_CONCURRENT + 1}/{(len(urls) + MAX_CONCURRENT - 1) // MAX_CONCURRENT} ({len(batch)} URLs)...")

            articles = await fetch_batch(client, batch)
            all_articles.extend(articles)
            print(f"  Got {len(articles)} articles (total: {len(all_articles)})")

            # Rate limiting
            await asyncio.sleep(DELAY_BETWEEN_BATCHES)

    print()
    print(f"Total articles fetched: {len(all_articles)}")

    # Convert to dict format expected by collector
    articles_dict = {a["link"]: a for a in all_articles}

    # Save
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w") as f:
        json.dump(articles_dict, f, indent=2, ensure_ascii=False)

    print(f"Saved to {OUTPUT_FILE}")

    # Print some stats
    jan_articles = [a for a in all_articles if a.get("published_date", "").startswith("2026-01")]
    print(f"Articles with January 2026 date: {len(jan_articles)}")


if __name__ == "__main__":
    asyncio.run(main())
