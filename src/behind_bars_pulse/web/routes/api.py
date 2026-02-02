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
    from behind_bars_pulse.services.newsletter_service import NewsletterService

    log.info("api_generate_start", date=collection_date.isoformat())
    try:
        with NewsletterGenerator() as generator:
            newsletter_content, press_review, enriched_articles = generator.generate(
                collection_date=collection_date,
                days_back=7,
                first_issue=False,
            )

            today_str = collection_date.strftime("%d.%m.%Y")
            context = generator.build_context(newsletter_content, press_review, today_str)

            # Save preview to files/GCS
            sender = EmailSender()
            html_path = sender.save_preview(context, issue_date=collection_date)

            # Read rendered content for DB storage
            html_content = html_path.read_text(encoding="utf-8") if html_path.exists() else None
            txt_path = html_path.with_suffix(".txt").with_name(
                html_path.name.replace(".html", ".txt")
            )
            txt_content = txt_path.read_text(encoding="utf-8") if txt_path.exists() else None

            # Save to database
            newsletter_service = NewsletterService()
            asyncio.run(
                newsletter_service.save_newsletter(
                    context=context,
                    enriched_articles=list(enriched_articles.values()),
                    press_review=press_review,
                    html_content=html_content,
                    txt_content=txt_content,
                    issue_date=collection_date,
                    generate_embeddings=False,  # Articles already have embeddings from collect
                )
            )

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


@router.post("/import-newsletters", response_model=TaskResponse)
async def api_import_newsletters(
    background_tasks: BackgroundTasks,
    admin_token: str | None = None,
):
    """Import existing newsletter HTML files from GCS into the database.

    One-time admin endpoint to backfill newsletters.
    Requires admin_token query parameter matching GEMINI_API_KEY (as a simple auth).
    """
    from behind_bars_pulse.config import get_settings

    settings = get_settings()
    expected_token = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None

    if not admin_token or admin_token != expected_token:
        from fastapi import HTTPException
        raise HTTPException(status_code=403, detail="Invalid admin token")

    log.info("api_import_newsletters_triggered")
    background_tasks.add_task(_run_import_newsletters)

    return TaskResponse(
        status="accepted",
        message="Newsletter import started",
    )


def _run_import_newsletters() -> None:
    """Import newsletters from GCS into the database.

    Creates a fresh database engine to avoid event loop conflicts.
    """
    import re
    from datetime import datetime

    from bs4 import BeautifulSoup
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from behind_bars_pulse.config import get_settings
    from behind_bars_pulse.db.models import Newsletter
    from behind_bars_pulse.services.storage import StorageService

    settings = get_settings()
    log.info("import_newsletters_start")

    if not settings.gcs_bucket:
        log.warning("import_newsletters_no_gcs_bucket")
        return

    storage = StorageService(settings.gcs_bucket)
    if not storage.is_enabled:
        log.warning("import_newsletters_storage_not_enabled")
        return

    # Create a fresh SYNC engine (not tied to FastAPI's event loop)
    sync_url = settings.database_url.replace("+asyncpg", "").replace("postgresql+", "postgresql://")
    if sync_url.startswith("postgresql://"):
        sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://", 1)
    engine = create_engine(sync_url)
    SessionLocal = sessionmaker(bind=engine)

    # List HTML files in GCS
    files = storage.list_files("previous_issues/")
    html_files = [f for f in files if f.endswith(".html") and "_issue" in f]
    log.info("import_newsletters_found_files", count=len(html_files))

    imported = 0
    for gcs_path in sorted(html_files):
        # Extract date from filename
        filename = gcs_path.split("/")[-1]
        match = re.match(r"(\d{8})_issue", filename)
        if not match:
            continue

        date_str = match.group(1)
        issue_date = datetime.strptime(date_str, "%Y%m%d").date()

        # Download content
        html_content = storage.download_content(gcs_path)
        if not html_content:
            continue

        txt_path = gcs_path.replace(".html", ".txt")
        txt_content = storage.download_content(txt_path) or ""

        # Parse HTML for title/subtitle
        soup = BeautifulSoup(html_content, "html.parser")
        title = "Behind Bars Pulse"
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)[:500]

        subtitle = f"Edizione del {issue_date.strftime('%d/%m/%Y')}"
        h2 = soup.find("h2")
        if h2:
            subtitle = h2.get_text(strip=True)[:1000]

        # Extract opening/closing
        opening = "Rassegna stampa sul sistema carcerario italiano."
        closing = "Grazie per averci letto."
        paragraphs = soup.find_all("p")
        for p in paragraphs:
            text = p.get_text(strip=True)
            if len(text) > 100:
                opening = text
                break

        # Save to database (sync)
        with SessionLocal() as session:
            existing = session.execute(
                select(Newsletter).where(Newsletter.issue_date == issue_date)
            ).scalar_one_or_none()

            if existing:
                log.info("newsletter_already_exists", date=issue_date)
                continue

            newsletter = Newsletter(
                issue_date=issue_date,
                title=title,
                subtitle=subtitle,
                opening=opening,
                closing=closing,
                html_content=html_content,
                txt_content=txt_content,
                press_review=None,
            )
            session.add(newsletter)
            session.commit()

        log.info("newsletter_imported", date=issue_date)
        imported += 1

    engine.dispose()
    log.info("import_newsletters_complete", imported=imported)


def _run_regenerate(collection_date: date, days_back: int, first_issue: bool) -> None:
    """Regenerate a newsletter with full AI pipeline.

    Creates a fresh database engine to avoid event loop conflicts.
    """
    from sqlalchemy import create_engine, delete
    from sqlalchemy.orm import sessionmaker

    from behind_bars_pulse.config import get_settings
    from behind_bars_pulse.db.models import Newsletter
    from behind_bars_pulse.email.sender import EmailSender
    from behind_bars_pulse.newsletter.generator import NewsletterGenerator

    settings = get_settings()
    log.info(
        "api_regenerate_start",
        date=collection_date.isoformat(),
        days_back=days_back,
        first_issue=first_issue,
    )

    try:
        # Delete existing newsletter for this date (sync, fresh connection)
        sync_url = settings.database_url.replace("+asyncpg", "").replace(
            "postgresql+", "postgresql://"
        )
        if sync_url.startswith("postgresql://"):
            sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://", 1)
        engine = create_engine(sync_url)
        SessionLocal = sessionmaker(bind=engine)

        with SessionLocal() as session:
            session.execute(delete(Newsletter).where(Newsletter.issue_date == collection_date))
            session.commit()
            log.info("deleted_existing_newsletter", date=collection_date.isoformat())

        engine.dispose()

        # Generate new newsletter
        with NewsletterGenerator() as generator:
            newsletter_content, press_review, enriched_articles = generator.generate(
                collection_date=collection_date,
                days_back=days_back,
                first_issue=first_issue,
            )

            today_str = collection_date.strftime("%d.%m.%Y")
            context = generator.build_context(newsletter_content, press_review, today_str)

            # Save preview to files/GCS
            sender = EmailSender()
            html_path = sender.save_preview(context, issue_date=collection_date)

            # Read rendered content for DB storage
            html_content = html_path.read_text(encoding="utf-8") if html_path.exists() else None
            txt_path = html_path.with_name(html_path.name.replace(".html", ".txt"))
            txt_content = txt_path.read_text(encoding="utf-8") if txt_path.exists() else None

            # Save to database (sync to avoid event loop issues)
            from behind_bars_pulse.db.models import Newsletter as NewsletterModel

            engine = create_engine(sync_url)
            SessionLocal = sessionmaker(bind=engine)

            with SessionLocal() as session:
                # Convert press_review (list of Category) to dict for JSON storage
                # Use mode='json' to properly serialize dates as ISO strings
                press_review_data = None
                if press_review:
                    press_review_data = [cat.model_dump(mode="json") for cat in press_review]

                newsletter = NewsletterModel(
                    issue_date=collection_date,
                    title=newsletter_content.title,
                    subtitle=newsletter_content.subtitle,
                    opening=newsletter_content.opening,
                    closing=newsletter_content.closing,
                    html_content=html_content,
                    txt_content=txt_content,
                    press_review=press_review_data,
                )
                session.add(newsletter)
                session.commit()
                log.info("newsletter_saved", date=collection_date.isoformat())

            engine.dispose()

        log.info("api_regenerate_complete", date=collection_date.isoformat())

    except Exception:
        log.exception("api_regenerate_failed")


@router.post("/regenerate", response_model=TaskResponse)
async def api_regenerate(
    background_tasks: BackgroundTasks,
    admin_token: str | None = None,
    collection_date: str | None = None,
    days_back: int = 7,
    first_issue: bool = False,
):
    """Regenerate a newsletter with full AI pipeline.

    Admin endpoint for regenerating past newsletters.
    Requires admin_token query parameter matching GEMINI_API_KEY.

    Parameters:
    - collection_date: Date to generate for (YYYY-MM-DD), defaults to today
    - days_back: Number of days to look back for articles (default: 7)
    - first_issue: Include introductory text for first edition (default: false)
    """
    from behind_bars_pulse.config import get_settings

    settings = get_settings()
    expected_token = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None

    if not admin_token or admin_token != expected_token:
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Invalid admin token")

    target_date = date.fromisoformat(collection_date) if collection_date else date.today()

    log.info(
        "api_regenerate_triggered",
        date=target_date.isoformat(),
        days_back=days_back,
        first_issue=first_issue,
    )
    background_tasks.add_task(_run_regenerate, target_date, days_back, first_issue)

    return TaskResponse(
        status="accepted",
        message=f"Regeneration started for {target_date.isoformat()} (days_back={days_back}, first_issue={first_issue})",
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
