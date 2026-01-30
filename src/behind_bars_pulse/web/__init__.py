# ABOUTME: Web module initialization.
# ABOUTME: Exports FastAPI app factory for the web frontend.

from behind_bars_pulse.web.app import create_app

__all__ = ["create_app"]
