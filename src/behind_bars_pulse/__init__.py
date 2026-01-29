# ABOUTME: Main package for BehindBarsPulse newsletter generation system.
# ABOUTME: Exports core functionality for RSS processing, AI analysis, and email delivery.

from behind_bars_pulse.config import get_settings
from behind_bars_pulse.models import Article, EnrichedArticle, NewsletterContent, PressReview

__all__ = [
    "get_settings",
    "Article",
    "EnrichedArticle",
    "NewsletterContent",
    "PressReview",
]
