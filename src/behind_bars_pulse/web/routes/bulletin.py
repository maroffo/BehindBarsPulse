# ABOUTME: Bulletin routes for viewing daily editorial commentaries.
# ABOUTME: Provides latest, archive, and detail pages for bulletins.

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.web.dependencies import BulletinRepo, Templates

router = APIRouter(prefix="/bollettino")

ITEMS_PER_PAGE = 10


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
async def bulletin_archive(
    request: Request,
    templates: Templates,
    bulletin_repo: BulletinRepo,
    page: int = Query(1, ge=1),
):
    """List all bulletins with pagination."""
    offset = (page - 1) * ITEMS_PER_PAGE
    bulletins = await bulletin_repo.list_recent(
        limit=ITEMS_PER_PAGE + 1,
        offset=offset,
    )

    has_more = len(bulletins) > ITEMS_PER_PAGE
    if has_more:
        bulletins = bulletins[:ITEMS_PER_PAGE]

    return templates.TemplateResponse(
        request=request,
        name="bulletin_archive.html",
        context={
            "bulletins": bulletins,
            "page": page,
            "has_more": has_more,
        },
    )


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
