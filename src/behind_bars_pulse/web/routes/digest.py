# ABOUTME: Digest routes for viewing weekly editorial summaries.
# ABOUTME: Provides latest, archive redirect, and detail pages for weekly digests.

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.web.dependencies import Templates, WeeklyDigestRepo

router = APIRouter(prefix="/digest")


@router.get("", response_class=HTMLResponse)
async def digest_latest(
    request: Request,
    templates: Templates,
    digest_repo: WeeklyDigestRepo,
):
    """Display the latest weekly digest."""
    digest = await digest_repo.get_latest()

    if not digest:
        return templates.TemplateResponse(
            request=request,
            name="digest_empty.html",
            context={},
        )

    # Get adjacent digests for navigation
    prev_digest = await digest_repo.get_previous(digest.week_end)

    return templates.TemplateResponse(
        request=request,
        name="digest.html",
        context={
            "digest": digest,
            "prev_digest": prev_digest,
            "next_digest": None,
        },
    )


@router.get("/archivio", response_class=HTMLResponse)
async def digest_archive(page: int = Query(1, ge=1)):
    """Redirect to /edizioni/digest for backwards compatibility."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url=f"/edizioni/digest?page={page}", status_code=301)


@router.get("/{date_str}", response_class=HTMLResponse)
async def digest_detail(
    request: Request,
    date_str: str,
    templates: Templates,
    digest_repo: WeeklyDigestRepo,
):
    """Display a specific weekly digest by week_end date."""
    try:
        week_end = datetime.strptime(date_str, "%Y-%m-%d").date()
    except ValueError as e:
        raise HTTPException(
            status_code=400, detail="Formato data non valido. Usa YYYY-MM-DD."
        ) from e

    digest = await digest_repo.get_by_week_end(week_end)
    if not digest:
        raise HTTPException(status_code=404, detail="Digest settimanale non trovato.")

    # Get adjacent digests for navigation
    prev_digest = await digest_repo.get_previous(week_end)
    next_digest = await digest_repo.get_next(week_end)

    return templates.TemplateResponse(
        request=request,
        name="digest.html",
        context={
            "digest": digest,
            "prev_digest": prev_digest,
            "next_digest": next_digest,
        },
    )
