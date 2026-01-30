# ABOUTME: Routes module initialization.
# ABOUTME: Exports all route modules for FastAPI app.

from behind_bars_pulse.web.routes import archive, articles, home, search

__all__ = ["archive", "articles", "home", "search"]
