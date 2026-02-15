# ABOUTME: API routes for Cloud Scheduler automation.
# ABOUTME: Endpoints for collect, generate, weekly, and health check.

from datetime import date
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
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
    """Run article collection in background.

    Uses batch inference when GCS bucket is configured (production),
    falls back to online collection when not (local dev).
    """
    from behind_bars_pulse.collector import ArticleCollector
    from behind_bars_pulse.config import get_settings

    settings = get_settings()
    log.info("api_collect_start", date=collection_date.isoformat(), batch=bool(settings.gcs_bucket))

    try:
        with ArticleCollector() as collector:
            if settings.gcs_bucket:
                result = collector.collect_batch(collection_date)
                log.info("api_collect_batch_submitted", **result)
            else:
                enriched = collector.collect(collection_date)
                log.info("api_collect_complete", articles=len(enriched))
    except Exception:
        log.exception("api_collect_failed")


def _run_weekly(reference_date: date) -> None:
    """Run weekly digest and send in background.

    Uses sync DB access to avoid event loop conflicts in background tasks.
    """
    from datetime import timedelta

    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session, sessionmaker

    from behind_bars_pulse.config import get_settings, make_sync_url
    from behind_bars_pulse.db.models import Bulletin as BulletinORM
    from behind_bars_pulse.db.models import Subscriber
    from behind_bars_pulse.db.models import WeeklyDigest as WeeklyDigestORM
    from behind_bars_pulse.email.sender import EmailSender
    from behind_bars_pulse.newsletter.weekly import WeeklyDigestGenerator

    log.info("api_weekly_start", date=reference_date.isoformat())

    settings = get_settings()
    generator = WeeklyDigestGenerator(settings)
    lookback = generator.settings.weekly_lookback_days
    week_end = reference_date
    week_start = reference_date - timedelta(days=lookback - 1)

    try:
        # Sync DB access (background tasks can't share the async engine)
        sync_url = make_sync_url(settings.database_url)
        engine = create_engine(sync_url)
        try:
            SessionLocal = sessionmaker(bind=engine)

            with SessionLocal() as session:
                bulletins = list(
                    session.execute(
                        select(BulletinORM)
                        .where(
                            BulletinORM.issue_date >= week_start,
                            BulletinORM.issue_date <= week_end,
                        )
                        .order_by(BulletinORM.issue_date.asc())
                    )
                    .scalars()
                    .all()
                )

                recipients = list(
                    session.execute(
                        select(Subscriber.email)
                        .where(Subscriber.confirmed == True)  # noqa: E712
                        .where(Subscriber.unsubscribed_at.is_(None))
                    )
                    .scalars()
                    .all()
                )

            log.info("weekly_data_loaded", bulletins=len(bulletins), recipients=len(recipients))

            if not bulletins:
                log.warning("api_weekly_no_bulletins")
                return

            content = generator.generate(bulletins=bulletins, reference_date=reference_date)
            email_context = generator.build_email_context(content, week_start, week_end)

            # Save WeeklyDigest to DB
            with Session(engine) as session:
                existing = (
                    session.query(WeeklyDigestORM)
                    .filter(WeeklyDigestORM.week_end == week_end)
                    .first()
                )
                if existing:
                    session.delete(existing)
                    session.commit()

                digest = WeeklyDigestORM(
                    week_start=week_start,
                    week_end=week_end,
                    title=content.weekly_title,
                    subtitle=content.weekly_subtitle or None,
                    narrative_arcs=content.narrative_arcs,
                    weekly_reflection=content.weekly_reflection,
                    upcoming_events=content.upcoming_events,
                )
                session.add(digest)
                session.commit()
                log.info("weekly_digest_saved", week_end=week_end.isoformat(), id=digest.id)
        finally:
            engine.dispose()

        if not recipients:
            log.warning("api_weekly_no_subscribers")
            return

        sender = EmailSender()
        sender.send(
            email_context,
            recipients=recipients,
            html_template="weekly_digest_template.html",
            txt_template="weekly_digest_template.txt",
        )
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

    from behind_bars_pulse.config import get_settings, make_sync_url
    from behind_bars_pulse.db.models import Article
    from behind_bars_pulse.models import EnrichedArticle

    settings = get_settings()
    if not settings.database_url:
        raise ValueError("Database not configured")

    # Use sync database connection
    sync_url = make_sync_url(settings.database_url)
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
            author=article.author or "",
            source=article.source or "",
            summary=article.summary or "",
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

    from behind_bars_pulse.config import get_settings, make_sync_url
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
    sync_url = make_sync_url(settings.database_url)
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

    from behind_bars_pulse.config import get_settings, make_sync_url
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
        sync_url = make_sync_url(settings.database_url)
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

                # Sanitize strings to remove NUL characters (PostgreSQL doesn't accept them)
                def sanitize_str(s: str | None) -> str | None:
                    return s.replace("\x00", "") if s else s

                def sanitize_json(obj: Any) -> Any:
                    """Recursively sanitize NUL chars from JSON-serializable data."""
                    if isinstance(obj, str):
                        return obj.replace("\x00", "")
                    elif isinstance(obj, dict):
                        return {k: sanitize_json(v) for k, v in obj.items()}
                    elif isinstance(obj, list):
                        return [sanitize_json(item) for item in obj]
                    return obj

                if press_review_data:
                    press_review_data = sanitize_json(press_review_data)

                newsletter = NewsletterModel(
                    issue_date=collection_date,
                    title=sanitize_str(newsletter_content.title),
                    subtitle=sanitize_str(newsletter_content.subtitle),
                    opening=sanitize_str(newsletter_content.opening),
                    closing=sanitize_str(newsletter_content.closing),
                    html_content=sanitize_str(html_content),
                    txt_content=sanitize_str(txt_content),
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


def _run_bulletin(issue_date: date) -> None:
    """Generate and save a bulletin in background."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    from behind_bars_pulse.bulletin.generator import BulletinGenerator
    from behind_bars_pulse.config import get_settings, make_sync_url
    from behind_bars_pulse.db.models import Bulletin as BulletinORM
    from behind_bars_pulse.db.models import EditorialComment as EditorialCommentORM
    from behind_bars_pulse.services.embedding_service import EmbeddingService

    settings = get_settings()
    log.info("api_bulletin_start", date=issue_date.isoformat())

    try:
        # Generate bulletin
        generator = BulletinGenerator(settings)
        bulletin = generator.generate(issue_date)

        if not bulletin:
            log.warning("api_bulletin_no_articles", date=issue_date.isoformat())
            return

        # Save to database
        sync_url = make_sync_url(settings.database_url)
        engine = create_engine(sync_url)

        with Session(engine) as session:
            # Delete existing bulletin for this date
            existing = (
                session.query(BulletinORM).filter(BulletinORM.issue_date == issue_date).first()
            )
            if existing:
                # Also delete associated editorial comments
                session.query(EditorialCommentORM).filter(
                    EditorialCommentORM.source_type == "bulletin",
                    EditorialCommentORM.source_id == existing.id,
                ).delete()
                session.delete(existing)
                session.commit()

            # Sanitize NUL characters (PostgreSQL doesn't accept them)
            def sanitize_str(s: str | None) -> str | None:
                return s.replace("\x00", "") if s else s

            def sanitize_json(obj: Any) -> Any:
                """Recursively sanitize NUL chars from JSON-serializable data."""
                if isinstance(obj, str):
                    return obj.replace("\x00", "")
                elif isinstance(obj, dict):
                    return {k: sanitize_json(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [sanitize_json(item) for item in obj]
                return obj

            # Sanitize press_review if present
            press_review_data = None
            if bulletin.press_review:
                press_review_data = sanitize_json(bulletin.press_review)

            # Create new bulletin
            db_bulletin = BulletinORM(
                issue_date=bulletin.issue_date,
                title=sanitize_str(bulletin.title),
                subtitle=sanitize_str(bulletin.subtitle),
                content=sanitize_str(bulletin.content),
                press_review=press_review_data,
                articles_count=bulletin.articles_count,
            )

            # Generate embedding for bulletin
            try:
                embedding_service = EmbeddingService()
                embedding = embedding_service._embed_text(bulletin.content)
                if embedding:
                    db_bulletin.embedding = embedding
            except Exception as e:
                log.warning("bulletin_embedding_failed", error=str(e))

            session.add(db_bulletin)
            session.flush()

            # Extract and save editorial comments
            comment_chunks = generator.extract_editorial_comments(bulletin, db_bulletin.id)
            for chunk in comment_chunks:
                db_comment = EditorialCommentORM(
                    source_type=chunk.source_type,
                    source_id=chunk.source_id,
                    source_date=chunk.source_date,
                    category=chunk.category,
                    content=chunk.content,
                )

                # Generate embedding for comment
                try:
                    embedding = embedding_service._embed_text(chunk.content)
                    if embedding:
                        db_comment.embedding = embedding
                except Exception as e:
                    log.warning("comment_embedding_failed", error=str(e))

                session.add(db_comment)

            session.commit()
            log.info("api_bulletin_complete", date=issue_date.isoformat(), id=db_bulletin.id)

        engine.dispose()

    except Exception:
        log.exception("api_bulletin_failed")


@router.post("/bulletin", response_model=TaskResponse)
async def api_bulletin(
    background_tasks: BackgroundTasks,
    _verified: OIDCVerified,
    issue_date: str | None = None,
):
    """Trigger daily bulletin generation.

    This endpoint is called by Cloud Scheduler daily at 8:00.
    Analyzes articles from the previous day and generates an editorial bulletin.
    """
    target_date = date.fromisoformat(issue_date) if issue_date else date.today()

    log.info("api_bulletin_triggered", date=target_date.isoformat())
    background_tasks.add_task(_run_bulletin, target_date)

    return TaskResponse(
        status="accepted",
        message=f"Bulletin generation started for {target_date.isoformat()}",
    )


@router.post("/bulletin-admin", response_model=TaskResponse)
async def api_bulletin_admin(
    background_tasks: BackgroundTasks,
    admin_token: str | None = None,
    issue_date: str | None = None,
):
    """Admin endpoint to generate a bulletin for a specific date.

    Requires admin_token query parameter matching GEMINI_API_KEY.
    """
    from behind_bars_pulse.config import get_settings

    settings = get_settings()
    expected_token = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None

    if not admin_token or admin_token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")

    target_date = date.fromisoformat(issue_date) if issue_date else date.today()

    log.info("api_bulletin_admin_triggered", date=target_date.isoformat())
    background_tasks.add_task(_run_bulletin, target_date)

    return TaskResponse(
        status="accepted",
        message=f"Bulletin generation started for {target_date.isoformat()}",
    )


def _run_regenerate_embeddings() -> None:
    """Regenerate all article and editorial comment embeddings with current model."""
    import time

    from google import genai
    from google.genai.types import EmbedContentConfig
    from sqlalchemy import create_engine, select, update
    from sqlalchemy.orm import sessionmaker

    from behind_bars_pulse.config import get_settings, make_sync_url
    from behind_bars_pulse.db.models import Article, EditorialComment
    from behind_bars_pulse.services.embedding_service import EMBEDDING_MODEL

    settings = get_settings()
    log.info("regenerate_embeddings_start", model=EMBEDDING_MODEL)

    if not settings.gemini_api_key:
        log.error("regenerate_embeddings_no_api_key")
        return

    client = genai.Client(api_key=settings.gemini_api_key.get_secret_value())

    sync_url = make_sync_url(settings.database_url)
    engine = create_engine(sync_url)
    Session = sessionmaker(bind=engine)

    def embed(text: str, task_type: str = "RETRIEVAL_DOCUMENT") -> list[float]:
        response = client.models.embed_content(
            model=EMBEDDING_MODEL,
            contents=text,
            config=EmbedContentConfig(task_type=task_type, output_dimensionality=768),
        )
        return list(response.embeddings[0].values)

    # Regenerate article embeddings
    with Session() as session:
        articles = session.execute(select(Article).order_by(Article.id)).scalars().all()
        log.info("regenerate_articles_found", count=len(articles))

        updated = 0
        for i, article in enumerate(articles):
            text = article.title
            if article.summary:
                text = f"{article.title}. {article.summary}"
            try:
                embedding = embed(text)
                session.execute(
                    update(Article).where(Article.id == article.id).values(embedding=embedding)
                )
                updated += 1
                if (i + 1) % 10 == 0:
                    log.info("regenerate_articles_progress", current=i + 1, total=len(articles))
                if (i + 1) % 50 == 0:
                    session.commit()
                    time.sleep(1)
            except Exception as e:
                log.warning("regenerate_article_failed", article_id=article.id, error=str(e))
        session.commit()
        log.info("regenerate_articles_complete", updated=updated, total=len(articles))

    # Regenerate editorial comment embeddings
    with Session() as session:
        comments = (
            session.execute(select(EditorialComment).order_by(EditorialComment.id)).scalars().all()
        )
        log.info("regenerate_comments_found", count=len(comments))

        updated = 0
        for i, comment in enumerate(comments):
            try:
                embedding = embed(comment.content)
                session.execute(
                    update(EditorialComment)
                    .where(EditorialComment.id == comment.id)
                    .values(embedding=embedding)
                )
                updated += 1
                if (i + 1) % 50 == 0:
                    session.commit()
                    time.sleep(1)
            except Exception as e:
                log.warning("regenerate_comment_failed", comment_id=comment.id, error=str(e))
        session.commit()
        log.info("regenerate_comments_complete", updated=updated, total=len(comments))

    engine.dispose()
    log.info("regenerate_embeddings_complete")


@router.post("/regenerate-embeddings", response_model=TaskResponse)
async def api_regenerate_embeddings(
    background_tasks: BackgroundTasks,
    admin_token: str | None = None,
):
    """Regenerate all article and editorial comment embeddings.

    Use after changing embedding model. Runs in background.
    Requires admin_token query parameter matching GEMINI_API_KEY.
    """
    from behind_bars_pulse.config import get_settings

    settings = get_settings()
    expected_token = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None

    if not admin_token or admin_token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")

    log.info("api_regenerate_embeddings_triggered")
    background_tasks.add_task(_run_regenerate_embeddings)

    return TaskResponse(
        status="accepted",
        message="Embedding regeneration started in background",
    )


@router.post("/migrate", response_model=TaskResponse)
async def api_migrate(admin_token: str | None = None):
    """Run database migrations (Alembic upgrade head).

    Admin endpoint for running migrations after deployment.
    Requires admin_token query parameter matching GEMINI_API_KEY.

    IMPORTANT: Run this endpoint after deploying new code that includes
    database schema changes, BEFORE accessing any pages that use new columns.
    """
    from behind_bars_pulse.config import get_settings

    settings = get_settings()
    expected_token = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None

    if not admin_token or admin_token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")

    log.info("api_migrate_triggered")

    try:
        import subprocess
        import sys

        # Run alembic in a subprocess to avoid event loop conflicts
        # (env.py uses asyncio.run() which can't be called from FastAPI's loop)
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd="/app",
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            log.error("api_migrate_failed", stderr=result.stderr, stdout=result.stdout)
            raise HTTPException(
                status_code=500,
                detail=f"Migration failed: {result.stderr or result.stdout}",
            )

        log.info("api_migrate_complete", stdout=result.stdout)
        return TaskResponse(
            status="success",
            message="Database migrations completed successfully",
        )

    except subprocess.TimeoutExpired as e:
        log.exception("api_migrate_timeout")
        raise HTTPException(status_code=500, detail="Migration timed out") from e
    except Exception as e:
        log.exception("api_migrate_failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/normalize-facilities")
async def normalize_facilities(
    admin_token: str = Query(..., description="Admin authentication token"),
    dry_run: bool = Query(True, description="Preview changes without applying"),
) -> dict:
    """Normalize facility names in database to consolidate duplicates.

    This updates prison_events and facility_snapshots tables to use canonical
    facility names (e.g., "Brescia Canton Mombello" → "Canton Mombello (Brescia)").

    Requires admin_token query parameter matching GEMINI_API_KEY.

    Set dry_run=false to apply changes.
    """
    from collections import Counter

    from sqlalchemy import text

    from behind_bars_pulse.config import get_settings
    from behind_bars_pulse.db.session import get_session
    from behind_bars_pulse.utils.facilities import normalize_facility_name

    settings = get_settings()
    expected_token = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None

    if not admin_token or admin_token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")

    log.info("api_normalize_facilities_triggered", dry_run=dry_run)

    results = {
        "prison_events": {"before": 0, "after": 0, "changes": 0},
        "facility_snapshots": {"before": 0, "after": 0, "changes": 0},
        "sample_changes": [],
        "dry_run": dry_run,
    }

    try:
        async with get_session() as session:
            # Analyze and normalize prison_events
            events_result = await session.execute(
                text("SELECT id, facility FROM prison_events WHERE facility IS NOT NULL")
            )
            events = events_result.fetchall()

            before_counts: Counter = Counter()
            after_counts: Counter = Counter()
            event_changes = []

            for event_id, facility in events:
                before_counts[facility] += 1
                normalized = normalize_facility_name(facility)
                after_counts[normalized] += 1
                if facility != normalized:
                    event_changes.append((event_id, facility, normalized))

            results["prison_events"]["before"] = len(before_counts)
            results["prison_events"]["after"] = len(after_counts)
            results["prison_events"]["changes"] = len(event_changes)

            # Analyze and normalize facility_snapshots
            snaps_result = await session.execute(
                text("SELECT id, facility FROM facility_snapshots WHERE facility IS NOT NULL")
            )
            snapshots = snaps_result.fetchall()

            before_counts = Counter()
            after_counts = Counter()
            snap_changes = []

            for snap_id, facility in snapshots:
                before_counts[facility] += 1
                normalized = normalize_facility_name(facility)
                after_counts[normalized] += 1
                if facility != normalized:
                    snap_changes.append((snap_id, facility, normalized))

            results["facility_snapshots"]["before"] = len(before_counts)
            results["facility_snapshots"]["after"] = len(after_counts)
            results["facility_snapshots"]["changes"] = len(snap_changes)

            # Sample changes for preview
            all_changes = event_changes[:5] + snap_changes[:5]
            results["sample_changes"] = [
                {"id": c[0], "old": c[1], "new": c[2]} for c in all_changes[:10]
            ]

            # Apply changes if not dry run
            if not dry_run:
                for event_id, _, normalized in event_changes:
                    await session.execute(
                        text("UPDATE prison_events SET facility = :facility WHERE id = :id"),
                        {"facility": normalized, "id": event_id},
                    )

                for snap_id, _, normalized in snap_changes:
                    await session.execute(
                        text("UPDATE facility_snapshots SET facility = :facility WHERE id = :id"),
                        {"facility": normalized, "id": snap_id},
                    )

                await session.commit()
                log.info(
                    "api_normalize_facilities_applied",
                    events_updated=len(event_changes),
                    snapshots_updated=len(snap_changes),
                )

        return results

    except Exception as e:
        log.exception("api_normalize_facilities_failed")
        raise HTTPException(status_code=500, detail=str(e)) from e


@router.post("/cleanup-events")
async def cleanup_events(
    admin_token: str = Query(..., description="Admin authentication token"),
    dry_run: bool = Query(True, description="Preview changes without applying"),
) -> dict:
    """Clean up prison_events data quality issues.

    This fixes:
    1. Marks unmarked aggregate statistics (facility=NULL, count>1) as is_aggregate=True
    2. Removes duplicate events (same incident from multiple articles)

    Duplicates are identified by (date, normalized_facility, event_type).
    Keeps the record with the longest description.

    Requires admin_token query parameter matching GEMINI_API_KEY.
    Set dry_run=false to apply changes.
    """
    from collections import defaultdict

    from sqlalchemy import text

    from behind_bars_pulse.config import get_settings
    from behind_bars_pulse.db.session import get_session
    from behind_bars_pulse.utils.facilities import normalize_facility_name

    settings = get_settings()
    expected_token = settings.gemini_api_key.get_secret_value() if settings.gemini_api_key else None

    if not admin_token or admin_token != expected_token:
        raise HTTPException(status_code=403, detail="Invalid admin token")

    log.info("api_cleanup_events_triggered", dry_run=dry_run)

    results: dict = {
        "aggregates_marked": 0,
        "duplicates_removed": 0,
        "before_count": 0,
        "after_count": 0,
        "sample_duplicates": [],
        "dry_run": dry_run,
    }

    try:
        async with get_session() as session:
            # Get all events
            events_result = await session.execute(
                text("""
                    SELECT id, event_date, facility, event_type, count, description, is_aggregate
                    FROM prison_events
                    ORDER BY event_date, facility, event_type, id
                """)
            )
            events = events_result.fetchall()
            results["before_count"] = len(events)

            # Step 1: Find unmarked aggregates (facility=NULL, count>1, not already marked)
            aggregate_ids_to_mark = []
            for row in events:
                event_id, event_date, facility, event_type, count, description, is_agg = row
                if facility is None and count is not None and count > 1 and not is_agg:
                    aggregate_ids_to_mark.append(event_id)
            results["aggregates_marked"] = len(aggregate_ids_to_mark)

            # Step 2: Find duplicates by (date, normalized_facility, event_type)
            groups: dict = defaultdict(list)
            for row in events:
                event_id, event_date, facility, event_type, count, description, is_agg = row
                if is_agg or event_id in aggregate_ids_to_mark:
                    continue
                if event_date is None or facility is None:
                    continue

                normalized = normalize_facility_name(facility) or facility
                key = (str(event_date), normalized, event_type)
                groups[key].append(
                    {
                        "id": event_id,
                        "facility": facility,
                        "description": description or "",
                    }
                )

            duplicate_ids = []
            for key, event_list in groups.items():
                if len(event_list) > 1:
                    sorted_events = sorted(
                        event_list, key=lambda e: len(e["description"]), reverse=True
                    )
                    keep = sorted_events[0]
                    remove = sorted_events[1:]

                    if len(results["sample_duplicates"]) < 5:
                        results["sample_duplicates"].append(
                            {
                                "key": f"{key[0]} | {key[1]} | {key[2]}",
                                "keep_id": keep["id"],
                                "remove_ids": [r["id"] for r in remove],
                            }
                        )

                    duplicate_ids.extend(r["id"] for r in remove)

            results["duplicates_removed"] = len(duplicate_ids)
            results["after_count"] = results["before_count"] - len(duplicate_ids)

            # Apply changes
            if not dry_run:
                if aggregate_ids_to_mark:
                    await session.execute(
                        text("UPDATE prison_events SET is_aggregate = TRUE WHERE id = ANY(:ids)"),
                        {"ids": aggregate_ids_to_mark},
                    )

                if duplicate_ids:
                    await session.execute(
                        text("DELETE FROM prison_events WHERE id = ANY(:ids)"),
                        {"ids": duplicate_ids},
                    )

                await session.commit()
                log.info(
                    "api_cleanup_events_applied",
                    aggregates_marked=len(aggregate_ids_to_mark),
                    duplicates_removed=len(duplicate_ids),
                )

        return results

    except Exception as e:
        log.exception("api_cleanup_events_failed")
        raise HTTPException(status_code=500, detail=str(e)) from e
