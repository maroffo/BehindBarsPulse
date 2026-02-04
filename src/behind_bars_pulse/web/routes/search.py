# ABOUTME: Search routes with semantic search using embeddings.
# ABOUTME: Provides HTMX-powered search with vector similarity and pagination.

from dataclasses import dataclass
from enum import Enum

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.db.models import Article, EditorialComment
from behind_bars_pulse.web.dependencies import (
    ArticleRepo,
    EditorialCommentRepo,
    NewsletterSvc,
    Templates,
)

router = APIRouter(prefix="/search")
logger = structlog.get_logger()

PAGE_SIZE = 25


class ContentType(str, Enum):
    """Search content type filter."""

    ALL = "all"
    ARTICLES = "articles"
    EDITORIAL = "editorial"


@dataclass
class SearchResult:
    """Search result with article and similarity score."""

    article: Article
    similarity: float
    result_type: str = "article"


@dataclass
class EditorialSearchResult:
    """Search result for editorial comments."""

    comment: EditorialComment
    similarity: float
    result_type: str = "editorial"


@router.get("", response_class=HTMLResponse)
async def search_page(
    request: Request,
    templates: Templates,
    q: str | None = Query(None),
    content_type: str = Query("all"),
):
    """Display the search page."""
    return templates.TemplateResponse(
        request=request,
        name="search.html",
        context={
            "query": q,
            "results": [],
            "content_type": content_type,
        },
    )


@router.get("/results", response_class=HTMLResponse)
async def search_results(
    request: Request,
    templates: Templates,
    article_repo: ArticleRepo,
    editorial_repo: EditorialCommentRepo,
    newsletter_svc: NewsletterSvc,
    q: str = Query("", min_length=0),
    offset: int = Query(0, ge=0),
    content_type: str = Query("all"),
):
    """Perform semantic search and return results partial (HTMX)."""
    results: list[SearchResult | EditorialSearchResult] = []
    total = 0
    has_more = False

    if q.strip():
        try:
            # Generate embedding for query
            query_embedding = await newsletter_svc.generate_embedding(q)

            if content_type == ContentType.ARTICLES.value:
                # Search only articles
                similar, total = await article_repo.search_by_embedding(
                    embedding=query_embedding,
                    threshold=0.45,
                    min_results=20,
                    limit=PAGE_SIZE,
                    offset=offset,
                )
                results = [
                    SearchResult(article=article, similarity=score) for article, score in similar
                ]

            elif content_type == ContentType.EDITORIAL.value:
                # Search only editorial comments
                similar, total = await editorial_repo.search_by_embedding(
                    embedding=query_embedding,
                    threshold=0.45,
                    limit=PAGE_SIZE,
                    offset=offset,
                )
                results = [
                    EditorialSearchResult(comment=comment, similarity=score)
                    for comment, score in similar
                ]

            else:
                # Search both and merge results
                article_results, article_total = await article_repo.search_by_embedding(
                    embedding=query_embedding,
                    threshold=0.45,
                    min_results=10,
                    limit=PAGE_SIZE // 2,
                    offset=offset // 2,
                )
                editorial_results, editorial_total = await editorial_repo.search_by_embedding(
                    embedding=query_embedding,
                    threshold=0.45,
                    limit=PAGE_SIZE // 2,
                    offset=offset // 2,
                )

                # Combine and sort by similarity
                combined = []
                for article, score in article_results:
                    combined.append(SearchResult(article=article, similarity=score))
                for comment, score in editorial_results:
                    combined.append(EditorialSearchResult(comment=comment, similarity=score))

                combined.sort(key=lambda x: x.similarity, reverse=True)
                results = combined[:PAGE_SIZE]
                total = article_total + editorial_total

            has_more = (offset + len(results)) < total
            logger.info(
                "search_completed",
                query=q,
                content_type=content_type,
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
            "content_type": content_type,
        },
    )
