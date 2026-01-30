# ABOUTME: Search routes with semantic search using embeddings.
# ABOUTME: Provides HTMX-powered search with vector similarity.

from dataclasses import dataclass

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.db.models import Article
from behind_bars_pulse.web.dependencies import ArticleRepo, NewsletterSvc, Templates

router = APIRouter(prefix="/search")
logger = structlog.get_logger()


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
):
    """Perform semantic search and return results partial (HTMX)."""
    results: list[SearchResult] = []

    if q.strip():
        try:
            # Generate embedding for query
            query_embedding = await newsletter_svc.generate_embedding(q)

            # Search by embedding similarity
            similar = await article_repo.search_by_embedding(
                embedding=query_embedding,
                limit=10,
                threshold=0.5,  # Lower threshold for broader results
            )

            results = [
                SearchResult(article=article, similarity=score) for article, score in similar
            ]
            logger.info("search_completed", query=q, results_count=len(results))

        except Exception as e:
            logger.error("search_failed", query=q, error=str(e))
            # Return empty results on error

    return templates.TemplateResponse(
        request=request,
        name="partials/search_results.html",
        context={
            "query": q,
            "results": results,
        },
    )
