# ABOUTME: Bulletin routes for viewing daily editorial commentaries.
# ABOUTME: Provides latest, archive, and detail pages for bulletins.

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.db.models import Article
from behind_bars_pulse.web.dependencies import ArticleRepo, BulletinRepo, Templates

router = APIRouter(prefix="/bollettino")

ITEMS_PER_PAGE = 10


def _group_articles_by_category(
    articles: Sequence[Article],
) -> list[dict[str, str | list[Article]]]:
    """Group articles by category, maintaining order."""
    categories: dict[str, list[Article]] = defaultdict(list)
    for article in articles:
        cat = article.category or "Altro"
        categories[cat].append(article)

    # Convert to list of dicts for template
    return [{"category": cat, "articles": arts} for cat, arts in categories.items()]


@router.get("", response_class=HTMLResponse)
async def bulletin_latest(
    request: Request,
    templates: Templates,
    bulletin_repo: BulletinRepo,
    article_repo: ArticleRepo,
):
    """Display the latest bulletin."""
    bulletin = await bulletin_repo.get_latest()

    if not bulletin:
        # Show empty state if no bulletins yet
        return templates.TemplateResponse(
            request=request,
            name="bulletin_empty.html",
            context={},
        )

    # Get adjacent bulletins for navigation
    all_bulletins = await bulletin_repo.list_recent(limit=2)
    prev_bulletin = all_bulletins[1] if len(all_bulletins) > 1 else None

    # Load articles from the day before the bulletin
    articles_date = bulletin.issue_date - timedelta(days=1)
    articles = await article_repo.list_by_published_date(articles_date)
    categories = _group_articles_by_category(list(articles))

    return templates.TemplateResponse(
        request=request,
        name="bulletin.html",
        context={
            "bulletin": bulletin,
            "prev_bulletin": prev_bulletin,
            "next_bulletin": None,
            "categories": categories,
        },
    )


@router.get("/archivio", response_class=HTMLResponse)
async def bulletin_archive(page: int = Query(1, ge=1)):
    """Redirect to /edizioni/bollettino for backwards compatibility."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/edizioni/bollettino?page={page}", status_code=301)


@router.get("/{date_str}", response_class=HTMLResponse)
async def bulletin_detail(
    request: Request,
    date_str: str,
    templates: Templates,
    bulletin_repo: BulletinRepo,
    article_repo: ArticleRepo,
):
    """Display a specific bulletin by date."""
    try:
        issue_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail="Formato data non valido. Usa YYYY-MM-DD."
        ) from e

    bulletin = await bulletin_repo.get_by_date(issue_date)
    if not bulletin:
        raise HTTPException(status_code=404, detail="Bollettino non trovato.")

    # Get adjacent bulletins for navigation (efficient single-row queries)
    prev_bulletin = await bulletin_repo.get_previous(issue_date)
    next_bulletin = await bulletin_repo.get_next(issue_date)

    # Load articles from the day before the bulletin
    articles_date = issue_date - timedelta(days=1)
    articles = await article_repo.list_by_published_date(articles_date)
    categories = _group_articles_by_category(list(articles))

    return templates.TemplateResponse(
        request=request,
        name="bulletin.html",
        context={
            "bulletin": bulletin,
            "prev_bulletin": prev_bulletin,
            "next_bulletin": next_bulletin,
            "categories": categories,
        },
    )
