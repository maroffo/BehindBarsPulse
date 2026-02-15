# ABOUTME: Home page route with hero, subscribe CTA, and latest editions.
# ABOUTME: Displays project intro, subscription form, latest bulletin and weekly digest.

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.web.dependencies import BulletinRepo, Templates, WeeklyDigestRepo

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def landing(
    request: Request,
    templates: Templates,
    digest_repo: WeeklyDigestRepo,
    bulletin_repo: BulletinRepo,
):
    """Display the home page with subscription form and latest editions."""
    # Get latest digest and bulletin for preview
    latest_digest = await digest_repo.get_latest()

    latest_bulletin = await bulletin_repo.get_latest()

    return templates.TemplateResponse(
        request=request,
        name="landing.html",
        context={
            "latest_digest": latest_digest,
            "latest_bulletin": latest_bulletin,
        },
    )
