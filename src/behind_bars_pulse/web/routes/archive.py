# ABOUTME: Archive routes for browsing past newsletters.
# ABOUTME: Provides backwards-compatible redirects and individual newsletter detail pages.

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.web.dependencies import NewsletterRepo, Templates

router = APIRouter(prefix="/archive")


@router.get("", response_class=HTMLResponse)
async def archive_list(page: int = Query(1, ge=1)):
    """Redirect to /edizioni/newsletter for backwards compatibility."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/edizioni/newsletter?page={page}", status_code=301)


@router.get("/{date_str}", response_class=HTMLResponse)
async def archive_detail(
    request: Request,
    date_str: str,
    templates: Templates,
    newsletter_repo: NewsletterRepo,
):
    """Display a specific newsletter by date."""
    try:
        issue_date = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail="Formato data non valido. Usa YYYY-MM-DD."
        ) from e

    newsletter = await newsletter_repo.get_by_date(issue_date)
    if not newsletter:
        raise HTTPException(status_code=404, detail="Newsletter non trovata.")

    # Get adjacent newsletters for navigation
    all_newsletters = await newsletter_repo.list_recent(limit=100)
    sorted_dates = [n.issue_date for n in all_newsletters]

    prev_newsletter = None
    next_newsletter = None

    try:
        idx = sorted_dates.index(issue_date)
        if idx > 0:
            next_newsletter = all_newsletters[idx - 1]  # More recent
        if idx < len(sorted_dates) - 1:
            prev_newsletter = all_newsletters[idx + 1]  # Older
    except ValueError:
        pass

    return templates.TemplateResponse(
        request=request,
        name="newsletter.html",
        context={
            "newsletter": newsletter,
            "prev_newsletter": prev_newsletter,
            "next_newsletter": next_newsletter,
        },
    )
