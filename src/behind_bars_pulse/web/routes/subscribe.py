# ABOUTME: Subscription routes for newsletter signup flow.
# ABOUTME: Handles subscribe, confirm, and unsubscribe actions.

import structlog
from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse

from behind_bars_pulse.config import get_settings
from behind_bars_pulse.db.repository import SubscriberRepository
from behind_bars_pulse.email.sender import EmailSender
from behind_bars_pulse.services.subscriber_service import SubscriberService
from behind_bars_pulse.web.dependencies import DbSession, Templates

router = APIRouter()
log = structlog.get_logger()


@router.post("/subscribe", response_class=HTMLResponse)
async def subscribe(
    request: Request,
    session: DbSession,
    templates: Templates,
    email: str = Form(...),
):
    """Handle newsletter subscription request."""
    repo = SubscriberRepository(session)
    service = SubscriberService(repo)
    settings = get_settings()

    # Generic success message to prevent user enumeration attacks
    success_msg = (
        "Ti abbiamo inviato un'email di conferma. "
        "Controlla anche la cartella spam! "
        "Per non perdere le prossime newsletter, aggiungi info@behindbars.news ai tuoi contatti."
    )

    error_msg = None
    try:
        subscriber = await service.create_subscriber(email)

        # Send confirmation email
        confirm_url = f"{settings.app_base_url}/confirm/{subscriber.token}"
        sender = EmailSender(settings)
        sender.send_confirmation_email(subscriber.email, confirm_url)

        log.info("subscription_created", email=email)

    except ValueError:
        # Email already exists - log but don't reveal to user (prevents enumeration)
        log.debug("subscribe_duplicate", email=email)
    except Exception:
        log.exception("subscribe_email_send_failed", email=email)
        error_msg = (
            "Si è verificato un errore nell'invio dell'email di conferma. "
            "Riprova tra qualche minuto."
        )

    if error_msg:
        if request.headers.get("HX-Request"):
            return HTMLResponse(f'<div class="form-error">{error_msg}</div>')
        return templates.TemplateResponse(
            request=request,
            name="subscribe_success.html",
            context={"email": email, "error": error_msg},
        )

    # Always return same response to prevent user enumeration
    if request.headers.get("HX-Request"):
        return HTMLResponse(f'<div class="form-success">{success_msg}</div>')

    return templates.TemplateResponse(
        request=request,
        name="subscribe_success.html",
        context={"email": email},
    )


@router.get("/confirm/{token}", response_class=HTMLResponse)
async def confirm(
    request: Request,
    token: str,
    session: DbSession,
    templates: Templates,
):
    """Confirm email subscription."""
    repo = SubscriberRepository(session)
    service = SubscriberService(repo)

    subscriber = await service.confirm_subscriber(token)

    if subscriber:
        log.info("subscription_confirmed", email=subscriber.email)
        return templates.TemplateResponse(
            request=request,
            name="confirm_success.html",
            context={},
        )
    else:
        log.warning("confirm_invalid_token", token=token[:8] + "...")
        return templates.TemplateResponse(
            request=request,
            name="unsubscribe.html",
            context={"confirmed": False, "error": "Token non valido"},
            status_code=404,
        )


@router.get("/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe_get(
    request: Request,
    token: str,
    session: DbSession,
    templates: Templates,
):
    """Display unsubscribe confirmation page."""
    repo = SubscriberRepository(session)
    subscriber = await repo.get_by_token(token)

    if not subscriber:
        return templates.TemplateResponse(
            request=request,
            name="unsubscribe.html",
            context={"confirmed": False, "error": "Token non valido"},
            status_code=404,
        )

    return templates.TemplateResponse(
        request=request,
        name="unsubscribe.html",
        context={"confirmed": False},
    )


@router.post("/unsubscribe/{token}", response_class=HTMLResponse)
async def unsubscribe_post(
    request: Request,
    token: str,
    session: DbSession,
    templates: Templates,
):
    """Process unsubscribe request."""
    repo = SubscriberRepository(session)
    service = SubscriberService(repo)

    subscriber = await service.unsubscribe(token)

    if subscriber:
        log.info("unsubscribed", email=subscriber.email)
        return templates.TemplateResponse(
            request=request,
            name="unsubscribe.html",
            context={"confirmed": True},
        )
    else:
        return templates.TemplateResponse(
            request=request,
            name="unsubscribe.html",
            context={"confirmed": False, "error": "Token non valido"},
            status_code=404,
        )
