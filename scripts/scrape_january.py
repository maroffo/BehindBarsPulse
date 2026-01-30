# ABOUTME: Script to scrape ristretti.org articles from January 2026.
# ABOUTME: Fetches paginated archive pages and extracts article URLs.

import asyncio
import json
import re
from datetime import date
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://ristretti.org/"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "scraped_urls"


async def fetch_page(client: httpx.AsyncClient, start: int) -> str:
    """Fetch a single archive page."""
    url = f"{BASE_URL}?start={start}"
    response = await client.get(url)
    response.raise_for_status()
    return response.text


def extract_article_urls(html: str) -> list[str]:
    """Extract article URLs from archive page HTML."""
    soup = BeautifulSoup(html, "html.parser")
    urls = []

    # Find all links with itemprop="url" - these are the article links
    for link in soup.find_all("a", itemprop="url"):
        href = link.get("href", "")
        if href.startswith("/"):
            full_url = f"https://ristretti.org{href}"
            if full_url not in urls:
                urls.append(full_url)

    return urls


async def scrape_all_pages(max_start: int = 780, step: int = 10) -> list[str]:
    """Scrape all archive pages and collect article URLs."""
    all_urls = []

    async with httpx.AsyncClient(
        headers={"User-Agent": USER_AGENT},
        timeout=30.0,
        follow_redirects=True,
    ) as client:
        for start in range(0, max_start + 1, step):
            print(f"Fetching page ?start={start}...")
            try:
                html = await fetch_page(client, start)
                urls = extract_article_urls(html)
                print(f"  Found {len(urls)} article URLs")

                for url in urls:
                    if url not in all_urls:
                        all_urls.append(url)

                # Be polite - wait between requests
                await asyncio.sleep(0.5)

            except Exception as e:
                print(f"  Error fetching page: {e}")
                continue

    return all_urls


async def main():
    print("Starting scrape of ristretti.org January 2026 articles...")
    print("Pages: ?start=0 to ?start=780 (79 pages)")
    print()

    urls = await scrape_all_pages(max_start=780, step=10)

    print()
    print(f"Total unique article URLs found: {len(urls)}")

    # Save URLs to file
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "january_2026_urls.json"

    with open(output_file, "w") as f:
        json.dump({
            "scraped_date": str(date.today()),
            "total_urls": len(urls),
            "urls": urls,
        }, f, indent=2, ensure_ascii=False)

    print(f"Saved to {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
