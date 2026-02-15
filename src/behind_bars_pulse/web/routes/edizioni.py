# ABOUTME: Edizioni routes for overview of bulletins, digests, and newsletters.
# ABOUTME: Unified entry point for all editorial content archives.

from collections.abc import Awaitable, Callable, Sequence

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.web.dependencies import (
    BulletinRepo,
    NewsletterRepo,
    Templates,
    WeeklyDigestRepo,
)

router = APIRouter(prefix="/edizioni")

ITEMS_PER_PAGE = 10


async def _paginate[T](
    fetch_fn: Callable[[int, int], Awaitable[Sequence[T]]],
    page: int,
    per_page: int = ITEMS_PER_PAGE,
) -> tuple[list[T], bool]:
    """Fetch paginated items with has_more detection."""
    offset = (page - 1) * per_page
    items = await fetch_fn(per_page + 1, offset)
    has_more = len(items) > per_page
    return list(items[:per_page]), has_more


@router.get("", response_class=HTMLResponse)
async def edizioni_overview(
    request: Request,
    templates: Templates,
    bulletin_repo: BulletinRepo,
    digest_repo: WeeklyDigestRepo,
):
    """Overview page showing recent bulletins and digests."""
    bulletins = await bulletin_repo.list_recent(limit=5)
    digests = await digest_repo.list_recent(limit=5)

    return templates.TemplateResponse(
        request=request,
        name="edizioni.html",
        context={
            "bulletins": bulletins,
            "digests": digests,
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
    bulletins, has_more = await _paginate(bulletin_repo.list_recent, page)

    return templates.TemplateResponse(
        request=request,
        name="bulletin_archive.html",
        context={
            "bulletins": bulletins,
            "page": page,
            "has_more": has_more,
        },
    )


@router.get("/digest", response_class=HTMLResponse)
async def digest_archive(
    request: Request,
    templates: Templates,
    digest_repo: WeeklyDigestRepo,
    page: int = Query(1, ge=1),
):
    """List all weekly digests with pagination."""
    digests, has_more = await _paginate(digest_repo.list_recent, page)

    return templates.TemplateResponse(
        request=request,
        name="digest_archive.html",
        context={
            "digests": digests,
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
    newsletters, has_more = await _paginate(newsletter_repo.list_recent, page)

    return templates.TemplateResponse(
        request=request,
        name="archive.html",
        context={
            "newsletters": newsletters,
            "page": page,
            "has_more": has_more,
        },
    )
