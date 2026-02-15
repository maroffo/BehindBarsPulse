# ABOUTME: Legacy redirect from /latest to /digest.
# ABOUTME: Redirects to the latest weekly digest page.

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

router = APIRouter()


@router.get("/latest")
async def latest():
    """Redirect /latest to /digest."""
    return RedirectResponse(url="/digest", status_code=302)
