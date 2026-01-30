# ABOUTME: Home route displaying the latest newsletter.
# ABOUTME: Serves the main landing page with today's newsletter.

from datetime import date

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.web.dependencies import NewsletterRepo, Templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def home(
    request: Request,
    templates: Templates,
    newsletter_repo: NewsletterRepo,
):
    """Display the latest newsletter (today or most recent)."""
    # Try to get today's newsletter first
    newsletter = await newsletter_repo.get_by_date(date.today())

    # Fall back to most recent if none for today
    if not newsletter:
        recent = await newsletter_repo.list_recent(limit=1)
        newsletter = recent[0] if recent else None

    return templates.TemplateResponse(
        request=request,
        name="home.html",
        context={"newsletter": newsletter},
    )
