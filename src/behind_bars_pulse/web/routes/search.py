# ABOUTME: Search routes with semantic search using embeddings.
# ABOUTME: Provides HTMX-powered search with vector similarity and pagination.

from dataclasses import dataclass

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.db.models import Article
from behind_bars_pulse.web.dependencies import ArticleRepo, NewsletterSvc, Templates

router = APIRouter(prefix="/search")
logger = structlog.get_logger()

PAGE_SIZE = 25


@dataclass
class SearchResult:
    """Search result with article and similarity score."""

    article: Article
    similarity: float


@router.get("", response_class=HTMLResponse)
async def search_page(
    request: Request,
    templates: Templates,
    q: str | None = Query(None),
):
    """Display the search page."""
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "query": q,
            "results": [],
        },
    )


@router.get("/results", response_class=HTMLResponse)
async def search_results(
    request: Request,
    templates: Templates,
    article_repo: ArticleRepo,
    newsletter_svc: NewsletterSvc,
    q: str = Query("", min_length=0),
    offset: int = Query(0, ge=0),
):
    """Perform semantic search and return results partial (HTMX)."""
    results: list[SearchResult] = []
    total = 0
    has_more = False

    if q.strip():
        try:
            # Generate embedding for query
            query_embedding = await newsletter_svc.generate_embedding(q)

            # Search by embedding similarity (≥60% or min 10 results)
            similar, total = await article_repo.search_by_embedding(
                embedding=query_embedding,
                threshold=0.6,
                min_results=10,
                limit=PAGE_SIZE,
                offset=offset,
            )

            results = [
                SearchResult(article=article, similarity=score) for article, score in similar
            ]
            has_more = (offset + len(results)) < total
            logger.info(
                "search_completed",
                query=q,
                results_count=len(results),
                total=total,
                offset=offset,
            )

        except Exception as e:
            logger.error("search_failed", query=q, error=str(e))
            # Return empty results on error

    # Choose template based on whether this is initial load or "load more"
    template = "partials/search_results.html" if offset == 0 else "partials/search_more.html"

    return templates.TemplateResponse(
        request=request,
        name=template,
        context={
            "query": q,
            "results": results,
            "total": total,
            "offset": offset,
            "has_more": has_more,
            "next_offset": offset + PAGE_SIZE,
        },
    )
