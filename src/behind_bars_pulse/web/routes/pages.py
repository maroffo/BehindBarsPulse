# ABOUTME: Static page routes for about and contact pages.
# ABOUTME: Simple template rendering without database queries.

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.web.dependencies import Templates

router = APIRouter()


@router.get("/about", response_class=HTMLResponse)
async def about(request: Request, templates: Templates):
    """Display the about page."""
    return templates.TemplateResponse(
        request=request,
        name="about.html",
        context={},
    )


@router.get("/contact", response_class=HTMLResponse)
async def contact(request: Request, templates: Templates):
    """Display the contact page."""
    return templates.TemplateResponse(
        request=request,
        name="contact.html",
        context={},
    )
