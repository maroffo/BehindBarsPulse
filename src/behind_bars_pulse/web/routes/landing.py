# ABOUTME: Landing page route for the newsletter signup page.
# ABOUTME: Displays hero section, subscription form, and latest newsletter preview.

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.web.dependencies import NewsletterRepo, Templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def landing(
    request: Request,
    templates: Templates,
    newsletter_repo: NewsletterRepo,
):
    """Display the landing page with subscription form."""
    # Get latest newsletter for preview
    recent = await newsletter_repo.list_recent(limit=1)
    latest_newsletter = recent[0] if recent else None

    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={"latest_newsletter": latest_newsletter},
    )
