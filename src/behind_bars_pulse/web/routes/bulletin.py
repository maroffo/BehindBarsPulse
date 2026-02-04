# ABOUTME: Bulletin routes for viewing daily editorial commentaries.
# ABOUTME: Provides latest, archive, and detail pages for bulletins.

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.web.dependencies import BulletinRepo, Templates

router = APIRouter(prefix="/bollettino")


@router.get("", response_class=HTMLResponse)
async def bulletin_latest(
    request: Request,
    templates: Templates,
    bulletin_repo: BulletinRepo,
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

    return templates.TemplateResponse(
        request=request,
        name="bulletin.html",
        context={
            "bulletin": bulletin,
            "prev_bulletin": prev_bulletin,
            "next_bulletin": None,
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

    return templates.TemplateResponse(
        request=request,
        name="bulletin.html",
        context={
            "bulletin": bulletin,
            "prev_bulletin": prev_bulletin,
            "next_bulletin": next_bulletin,
        },
    )
