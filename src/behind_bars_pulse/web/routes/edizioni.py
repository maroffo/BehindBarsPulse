# ABOUTME: Edizioni routes for overview of bulletins and newsletters.
# ABOUTME: Unified entry point for all editorial content archives.

from collections.abc import Awaitable, Callable, Sequence

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.web.dependencies import BulletinRepo, NewsletterRepo, Templates

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
