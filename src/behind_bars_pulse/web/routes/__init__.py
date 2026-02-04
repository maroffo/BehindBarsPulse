# ABOUTME: Routes module initialization.
# ABOUTME: Exports all route modules for FastAPI app.

from behind_bars_pulse.web.routes import (
    api,
    archive,
    articles,
    bulletin,
    home,
    landing,
    pages,
    search,
    stats,
    subscribe,
)

__all__ = [
    "api",
    "archive",
    "articles",
    "bulletin",
    "home",
    "landing",
    "pages",
    "search",
    "stats",
    "subscribe",
]
