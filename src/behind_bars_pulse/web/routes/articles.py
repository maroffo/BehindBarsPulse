# ABOUTME: Article routes for browsing and viewing articles.
# ABOUTME: Provides list view with filtering and individual article detail.

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.web.dependencies import ArticleRepo, Templates

router = APIRouter()

ITEMS_PER_PAGE = 20


@router.get("/articles", response_class=HTMLResponse)
async def articles_list(
    request: Request,
    templates: Templates,
    article_repo: ArticleRepo,
    page: int = Query(1, ge=1),
    category: str | None = Query(None),
):
    """List all articles with optional category filtering and pagination."""
    offset = (page - 1) * ITEMS_PER_PAGE

    articles = await article_repo.list_recent(
        limit=ITEMS_PER_PAGE + 1,
        offset=offset,
        category=category,
    )

    has_more = len(articles) > ITEMS_PER_PAGE
    if has_more:
        articles = articles[:ITEMS_PER_PAGE]

    categories = await article_repo.list_categories()

    return templates.TemplateResponse(
        request=request,
        name="articles.html",
        context={
            "articles": articles,
            "categories": categories,
            "current_category": category,
            "page": page,
            "has_more": has_more,
        },
    )


@router.get("/articles/stats")
async def articles_stats(article_repo: ArticleRepo):
    """Debug endpoint to check article counts."""
    total = await article_repo.count()
    with_embeddings = await article_repo.count_with_embeddings()
    return {
        "total_articles": total,
        "with_embeddings": with_embeddings,
        "without_embeddings": total - with_embeddings,
    }


@router.get("/article/{article_id}", response_class=HTMLResponse)
async def article_detail(
    request: Request,
    article_id: int,
    templates: Templates,
    article_repo: ArticleRepo,
):
    """Display a single article with related articles."""
    article = await article_repo.get_by_id(article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Articolo non trovato.")

    # Find related articles using embedding similarity
    related_articles = []
    if article.embedding is not None:
        try:
            similar_results, _ = await article_repo.search_by_embedding(
                embedding=article.embedding,
                limit=4,  # Get one extra since current article might be included
                threshold=0.5,
            )
            # Filter out the current article, keep similarity score
            for art, similarity in similar_results:
                if art.id != article_id and len(related_articles) < 3:
                    art.similarity = similarity  # Attach similarity to article object
                    related_articles.append(art)
        except Exception:
            # Fallback to no related articles if search fails
            pass

    return templates.TemplateResponse(
        request=request,
        name="article.html",
        context={
            "article": article,
            "related_articles": related_articles,
        },
    )
