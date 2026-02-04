# ABOUTME: Home page route with hero, subscribe CTA, and latest editions.
# ABOUTME: Displays project intro, subscription form, latest bulletin and newsletter.

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.web.dependencies import BulletinRepo, NewsletterRepo, Templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def landing(
    request: Request,
    templates: Templates,
    newsletter_repo: NewsletterRepo,
    bulletin_repo: BulletinRepo,
):
    """Display the home page with subscription form and latest editions."""
    # Get latest newsletter and bulletin for preview
    recent_newsletters = await newsletter_repo.list_recent(limit=1)
    latest_newsletter = recent_newsletters[0] if recent_newsletters else None

    latest_bulletin = await bulletin_repo.get_latest()

    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={
            "latest_newsletter": latest_newsletter,
            "latest_bulletin": latest_bulletin,
        },
    )
