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


class BatchJobResponse(BaseModel):
    """Response model for batch job submission."""

    status: str
    job_name: str
    input_uri: str
    output_uri: str
    message: str


class BatchJobStatusResponse(BaseModel):
    """Response model for batch job status."""

    name: str
    state: str
    create_time: str | None
    update_time: str | None


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


def _load_articles_for_batch(end_date: date, days_back: int = 7) -> dict:
    """Load articles from database for batch job.

    Args:
        end_date: The end date of the range.
        days_back: Number of days to look back.

    Returns:
        Dictionary mapping URLs to EnrichedArticle objects.

    Raises:
        ValueError: If DB not configured or no articles found.
    """
    from datetime import timedelta

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import sessionmaker

    from behind_bars_pulse.config import get_settings
    from behind_bars_pulse.db.models import Article
    from behind_bars_pulse.models import EnrichedArticle

    settings = get_settings()
    if not settings.database_url:
        raise ValueError("Database not configured")

    # Use sync database connection
    sync_url = settings.database_url.replace("+asyncpg", "").replace("postgresql+", "postgresql://")
    if sync_url.startswith("postgresql://"):
        sync_url = sync_url.replace("postgresql://", "postgresql+psycopg2://", 1)

    engine = create_engine(sync_url)
    SessionLocal = sessionmaker(bind=engine)

    start_date = end_date - timedelta(days=days_back - 1)

    with SessionLocal() as session:
        stmt = (
            select(Article)
            .where(Article.published_date >= start_date)
            .where(Article.published_date <= end_date)
            .order_by(Article.published_date.desc())
        )
        articles = session.execute(stmt).scalars().all()

    engine.dispose()

    if not articles:
        raise ValueError(f"No articles found for {start_date} to {end_date}")

    # Convert DB models to EnrichedArticle
    enriched: dict[str, EnrichedArticle] = {}
    for article in articles:
        enriched[article.link] = EnrichedArticle(
            title=article.title,
            link=article.link,
            content=article.content,
            author=article.author,
            source=article.source,
            summary=article.summary,
            published_date=article.published_date,
        )

    return enriched


def _run_batch_job_sync(
    target_date: date,
    days_back: int,
    first_issue: bool,
) -> dict:
    """Run batch job submission synchronously (for run_in_executor).

    All blocking I/O operations are contained here.
    """
    from behind_bars_pulse.ai.batch import BatchInferenceService
    from behind_bars_pulse.narrative.storage import NarrativeStorage
    from behind_bars_pulse.newsletter.generator import NewsletterGenerator

    # Load articles from DB (sync)
    articles = _load_articles_for_batch(target_date, days_back)
    log.info("batch_articles_loaded", count=len(articles))

    # Load previous issues (sync file I/O)
    with NewsletterGenerator() as generator:
        previous_issues = generator.read_previous_issues()

    # Load narrative context (sync)
    narrative_context = None
    try:
        storage = NarrativeStorage()
        context = storage.load_context()
        if context.ongoing_storylines or context.key_characters:
            narrative_context = context
    except Exception as e:
        log.warning("narrative_context_load_failed", error=str(e))

    # Build and submit batch job (sync GCS + API calls)
    batch_service = BatchInferenceService()
    requests = batch_service.build_newsletter_batch(
        articles=articles,
        previous_issues=previous_issues,
        narrative_context=narrative_context,
        first_issue=first_issue,
    )

    input_uri = batch_service.upload_batch_input(requests, target_date)
    result = batch_service.submit_batch_job(input_uri, target_date)

    return {
        "job_name": result.job_name,
        "input_uri": result.input_uri,
        "output_uri": result.output_uri,
        "article_count": len(articles),
    }


@router.post("/generate-batch", response_model=BatchJobResponse)
async def api_generate_batch(
    _verified: OIDCVerified,
    collection_date: str | None = None,
    days_back: int = 7,
    first_issue: bool = False,
):
    """Submit batch job for newsletter generation.

    This endpoint submits a Vertex AI batch job for newsletter generation.
    The job runs asynchronously and results are processed by a Cloud Function.

    Args:
        collection_date: End date for article collection (YYYY-MM-DD).
        days_back: Number of days to look back for articles.
        first_issue: Include introductory text for first edition.

    Returns:
        BatchJobResponse with job details for tracking.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    target_date = date.fromisoformat(collection_date) if collection_date else date.today()

    log.info(
        "api_generate_batch_triggered",
        date=target_date.isoformat(),
        days_back=days_back,
        first_issue=first_issue,
    )

    try:
        # Run blocking I/O in thread pool to avoid blocking event loop
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1) as executor:
            result = await loop.run_in_executor(
                executor,
                _run_batch_job_sync,
                target_date,
                days_back,
                first_issue,
            )

        return BatchJobResponse(
            status="submitted",
            job_name=result["job_name"],
            input_uri=result["input_uri"],
            output_uri=result["output_uri"],
            message=f"Batch job submitted for {target_date.isoformat()} with {result['article_count']} articles",
        )

    except Exception as e:
        log.exception("api_generate_batch_failed")
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail=str(e)) from e


@router.get("/batch-job/{job_name:path}", response_model=BatchJobStatusResponse)
async def api_batch_job_status(
    job_name: str,
    _verified: OIDCVerified,
):
    """Get status of a batch job.

    Args:
        job_name: The job name returned from /api/generate-batch.

    Returns:
        BatchJobStatusResponse with current job status.
    """
    from behind_bars_pulse.ai.batch import BatchInferenceService

    log.info("api_batch_job_status", job_name=job_name)

    try:
        batch_service = BatchInferenceService()
        status = batch_service.get_job_status(job_name)

        return BatchJobStatusResponse(
            name=status["name"],
            state=status["state"],
            create_time=status.get("create_time"),
            update_time=status.get("update_time"),
        )

    except Exception as e:
        log.exception("api_batch_job_status_failed")
        from fastapi import HTTPException

        raise HTTPException(status_code=500, detail=str(e)) from e


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
