# ABOUTME: API routes for Cloud Scheduler automation.
# ABOUTME: Endpoints for collect, generate, weekly, and health check.

import asyncio
from datetime import date

import structlog
from fastapi import APIRouter, BackgroundTasks
from pydantic import BaseModel

from behind_bars_pulse.web.middleware.oidc import OIDCVerified

router = APIRouter(prefix="/api", tags=["api"])
log = structlog.get_logger()


class TaskResponse(BaseModel):
    """Response model for async tasks."""

    status: str
    message: str


class HealthResponse(BaseModel):
    """Response model for health check."""

    status: str
    version: str = "0.1.0"


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint for load balancer."""
    return HealthResponse(status="healthy")


def _run_collect(collection_date: date) -> None:
    """Run article collection in background."""
    from behind_bars_pulse.collector import ArticleCollector

    log.info("api_collect_start", date=collection_date.isoformat())
    try:
        with ArticleCollector() as collector:
            enriched = collector.collect(collection_date)
        log.info("api_collect_complete", articles=len(enriched))
    except Exception:
        log.exception("api_collect_failed")


def _run_generate(collection_date: date) -> None:
    """Run newsletter generation in background."""
    from behind_bars_pulse.email.sender import EmailSender
    from behind_bars_pulse.newsletter.generator import NewsletterGenerator

    log.info("api_generate_start", date=collection_date.isoformat())
    try:
        with NewsletterGenerator() as generator:
            newsletter_content, press_review, _ = generator.generate(
                collection_date=collection_date,
                days_back=7,
                first_issue=False,
            )

            today_str = collection_date.strftime("%d.%m.%Y")
            context = generator.build_context(newsletter_content, press_review, today_str)

            sender = EmailSender()
            sender.save_preview(context, issue_date=collection_date)

        log.info("api_generate_complete")
    except Exception:
        log.exception("api_generate_failed")


def _run_weekly(reference_date: date) -> None:
    """Run weekly digest and send in background."""
    from datetime import timedelta

    from behind_bars_pulse.db.repository import SubscriberRepository
    from behind_bars_pulse.db.session import get_session
    from behind_bars_pulse.email.sender import EmailSender
    from behind_bars_pulse.newsletter.weekly import WeeklyDigestGenerator
    from behind_bars_pulse.services.subscriber_service import SubscriberService

    log.info("api_weekly_start", date=reference_date.isoformat())

    async def get_recipients() -> list[str]:
        async with get_session() as session:
            repo = SubscriberRepository(session)
            service = SubscriberService(repo)
            return await service.get_active_emails()

    try:
        generator = WeeklyDigestGenerator()
        content = generator.generate(reference_date=reference_date)

        week_end = reference_date
        week_start = reference_date - timedelta(days=generator.settings.weekly_lookback_days - 1)
        context = generator.build_context(content, week_start, week_end)

        # Get recipients from database
        recipients = asyncio.run(get_recipients())

        if not recipients:
            log.warning("api_weekly_no_subscribers")
            return

        sender = EmailSender()
        sender.send(context, recipients=recipients)
        log.info("api_weekly_complete", recipient_count=len(recipients))

    except Exception:
        log.exception("api_weekly_failed")


@router.post("/collect", response_model=TaskResponse)
async def api_collect(
    background_tasks: BackgroundTasks,
    _verified: OIDCVerified,
    collection_date: str | None = None,
):
    """Trigger article collection.

    This endpoint is called by Cloud Scheduler daily.
    """
    target_date = date.fromisoformat(collection_date) if collection_date else date.today()

    log.info("api_collect_triggered", date=target_date.isoformat())
    background_tasks.add_task(_run_collect, target_date)

    return TaskResponse(
        status="accepted",
        message=f"Collection started for {target_date.isoformat()}",
    )


@router.post("/generate", response_model=TaskResponse)
async def api_generate(
    background_tasks: BackgroundTasks,
    _verified: OIDCVerified,
    collection_date: str | None = None,
):
    """Trigger daily newsletter generation (archive only, no send).

    This endpoint is called by Cloud Scheduler daily after collect.
    """
    target_date = date.fromisoformat(collection_date) if collection_date else date.today()

    log.info("api_generate_triggered", date=target_date.isoformat())
    background_tasks.add_task(_run_generate, target_date)

    return TaskResponse(
        status="accepted",
        message=f"Generation started for {target_date.isoformat()}",
    )


@router.post("/weekly", response_model=TaskResponse)
async def api_weekly(
    background_tasks: BackgroundTasks,
    _verified: OIDCVerified,
    reference_date: str | None = None,
):
    """Trigger weekly digest generation and send to subscribers.

    This endpoint is called by Cloud Scheduler on Sundays.
    """
    target_date = date.fromisoformat(reference_date) if reference_date else date.today()

    log.info("api_weekly_triggered", date=target_date.isoformat())
    background_tasks.add_task(_run_weekly, target_date)

    return TaskResponse(
        status="accepted",
        message=f"Weekly digest started for {target_date.isoformat()}",
    )
