# ABOUTME: Edizioni routes for overview of bulletins and newsletters.
# ABOUTME: Unified entry point for all editorial content archives.

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.web.dependencies import BulletinRepo, NewsletterRepo, Templates

router = APIRouter(prefix="/edizioni")

ITEMS_PER_PAGE = 10


@router.get("", response_class=HTMLResponse)
async def edizioni_overview(
    request: Request,
    templates: Templates,
    bulletin_repo: BulletinRepo,
    newsletter_repo: NewsletterRepo,
):
    """Overview page showing recent bulletins and newsletters."""
    bulletins = await bulletin_repo.list_recent(limit=5)
    newsletters = await newsletter_repo.list_recent(limit=5)

    return templates.TemplateResponse(
        request=request,
        name="edizioni.html",
        context={
            "bulletins": bulletins,
            "newsletters": newsletters,
        },
    )


@router.get("/bollettino", response_class=HTMLResponse)
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


@router.get("/newsletter", response_class=HTMLResponse)
async def newsletter_archive(
    request: Request,
    templates: Templates,
    newsletter_repo: NewsletterRepo,
    page: int = Query(1, ge=1),
):
    """List all newsletters with pagination."""
    offset = (page - 1) * ITEMS_PER_PAGE
    newsletters = await newsletter_repo.list_recent(
        limit=ITEMS_PER_PAGE + 1,
        offset=offset,
    )

    has_more = len(newsletters) > ITEMS_PER_PAGE
    if has_more:
        newsletters = newsletters[:ITEMS_PER_PAGE]

    return templates.TemplateResponse(
        request=request,
        name="archive.html",
        context={
            "newsletters": newsletters,
            "page": page,
            "has_more": has_more,
        },
    )
