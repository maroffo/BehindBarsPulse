# ABOUTME: Script to import existing newsletter HTML files into the database.
# ABOUTME: Parses HTML files from previous_issues/ and creates Newsletter records.

import asyncio
import re
from datetime import date, datetime
from pathlib import Path

import structlog
from bs4 import BeautifulSoup

from behind_bars_pulse.db.models import Newsletter
from behind_bars_pulse.db.repository import NewsletterRepository
from behind_bars_pulse.db.session import get_session

log = structlog.get_logger()


def parse_newsletter_html(html_content: str, txt_content: str, issue_date: date) -> dict:
    """Extract newsletter data from HTML content."""
    soup = BeautifulSoup(html_content, "html.parser")

    # Try to extract title from h1 or title tag
    title = "Behind Bars Pulse"
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)

    # Try to extract subtitle
    subtitle = ""
    # Look for subtitle in common places
    subtitle_elem = soup.find(class_="subtitle") or soup.find("h2")
    if subtitle_elem:
        subtitle = subtitle_elem.get_text(strip=True)

    # Extract opening paragraph
    opening = ""
    # Try to find first substantial paragraph
    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if len(text) > 100:  # Skip short paragraphs
            opening = text
            break

    # Extract closing (usually the last paragraph before footer)
    closing = ""
    paragraphs = soup.find_all("p")
    for p in reversed(paragraphs):
        text = p.get_text(strip=True)
        if len(text) > 50 and "voltaire" not in text.lower():
            closing = text
            break

    # If we couldn't extract good data, use defaults
    if not subtitle:
        subtitle = f"Edizione del {issue_date.strftime('%d/%m/%Y')}"
    if not opening:
        opening = "Rassegna stampa sul sistema carcerario italiano."
    if not closing:
        closing = "Grazie per averci letto."

    return {
        "issue_date": issue_date,
        "title": title[:500],  # Limit to DB field size
        "subtitle": subtitle[:1000],
        "opening": opening,
        "closing": closing,
        "html_content": html_content,
        "txt_content": txt_content,
        "press_review": None,  # We don't have structured data
    }


async def import_newsletters(issues_dir: Path) -> int:
    """Import all newsletter HTML files from a directory."""
    imported = 0

    # Find all HTML files
    html_files = sorted(issues_dir.glob("*_issue*.html"))

    for html_path in html_files:
        # Extract date from filename (e.g., 20260128_issue_preview.html)
        match = re.match(r"(\d{8})_issue", html_path.name)
        if not match:
            log.warning("skipping_invalid_filename", file=html_path.name)
            continue

        date_str = match.group(1)
        issue_date = datetime.strptime(date_str, "%Y%m%d").date()

        # Read HTML content
        html_content = html_path.read_text(encoding="utf-8")

        # Try to find corresponding TXT file
        txt_path = html_path.with_suffix(".txt").with_name(
            html_path.name.replace(".html", ".txt")
        )
        txt_content = ""
        if txt_path.exists():
            txt_content = txt_path.read_text(encoding="utf-8")

        # Parse and create newsletter
        data = parse_newsletter_html(html_content, txt_content, issue_date)

        async with get_session() as session:
            repo = NewsletterRepository(session)

            # Check if already exists
            existing = await repo.get_by_date(issue_date)
            if existing:
                log.info("newsletter_already_exists", date=issue_date)
                continue

            # Create new newsletter
            newsletter = Newsletter(**data)
            await repo.save(newsletter)
            await session.commit()

            log.info("newsletter_imported", date=issue_date, title=data["title"][:50])
            imported += 1

    return imported


if __name__ == "__main__":
    issues_dir = Path("previous_issues")

    if not issues_dir.exists():
        print(f"Directory not found: {issues_dir}")
        exit(1)

    count = asyncio.run(import_newsletters(issues_dir))
    print(f"Imported {count} newsletters")
