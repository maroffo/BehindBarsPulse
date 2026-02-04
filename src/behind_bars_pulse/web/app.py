# ABOUTME: FastAPI application factory with Jinja2 templates and database lifespan.
# ABOUTME: Main entry point for the BehindBars web frontend.

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

import bleach
import markdown as md
import structlog
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from behind_bars_pulse.db.session import close_db, init_db
from behind_bars_pulse.web.routes import (
    api,
    archive,
    articles,
    bulletin,
    edizioni,
    home,
    landing,
    pages,
    search,
    stats,
    subscribe,
)

logger = structlog.get_logger()

# Template and static paths
WEB_DIR = Path(__file__).parent
TEMPLATES_DIR = WEB_DIR / "templates"
STATIC_DIR = WEB_DIR / "static"

# Allowed HTML tags for sanitization (safe subset for article content)
ALLOWED_TAGS = ["p", "br", "strong", "em", "b", "i", "a", "ul", "ol", "li", "blockquote"]
ALLOWED_ATTRS = {"a": ["href", "title"]}


def sanitize_html(value: str) -> Markup:
    """Sanitize HTML content to prevent XSS while allowing safe formatting."""
    clean = bleach.clean(value, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    return Markup(clean)


def format_date(value: str | date | None, fmt: str = "%d %b") -> str:
    """Format a date value (string or date object) for display."""
    if value is None:
        return ""
    if isinstance(value, str):
        try:
            parsed = date.fromisoformat(value)
        except ValueError:
            return value  # Return as-is if parsing fails
        return parsed.strftime(fmt)
    return value.strftime(fmt)


def render_markdown(value: str) -> Markup:
    """Convert markdown text to sanitized HTML."""
    html = md.markdown(value, extensions=["nl2br"])
    clean = bleach.clean(html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)
    return Markup(clean)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan context for database setup/teardown."""
    logger.info("app_startup")
    await init_db()
    yield
    logger.info("app_shutdown")
    await close_db()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="BehindBars",
        description="Newsletter quotidiana sul sistema carcerario italiano",
        version="0.1.0",
        lifespan=lifespan,
    )

    # Configure templates with custom filters
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
    templates.env.filters["sanitize"] = sanitize_html
    templates.env.filters["format_date"] = format_date
    templates.env.filters["markdown"] = render_markdown
    app.state.templates = templates

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    # Include routers
    app.include_router(landing.router)
    app.include_router(subscribe.router)
    app.include_router(pages.router)
    app.include_router(home.router)
    app.include_router(edizioni.router)
    app.include_router(archive.router)
    app.include_router(articles.router)
    app.include_router(bulletin.router)
    app.include_router(search.router)
    app.include_router(stats.router)
    app.include_router(api.router)

    return app


# Application instance for uvicorn
app = create_app()
