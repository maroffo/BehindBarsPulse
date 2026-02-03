# ABOUTME: Cloud Function to process Vertex AI batch job results.
# ABOUTME: Triggered by GCS Object Finalize when batch output is written.

import html
import json
import os
import re
from datetime import date

import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import secretmanager, storage
from sqlalchemy import Column, Date, Integer, String, Text, create_engine, delete
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, sessionmaker

# Database setup - global scope for connection reuse across invocations
Base = declarative_base()


class Newsletter(Base):
    """Newsletter model for database storage."""

    __tablename__ = "newsletters"

    id = Column(Integer, primary_key=True)
    issue_date = Column(Date, unique=True, nullable=False, index=True)
    title = Column(String(500), nullable=False)
    subtitle = Column(String(1000))
    opening = Column(Text)
    closing = Column(Text)
    html_content = Column(Text)
    txt_content = Column(Text)
    press_review = Column(JSONB)


# Global engine for connection reuse (warm starts)
_engine = None
_session_factory = None
_sm_client = None


def _get_secret(secret_resource_name: str) -> str:
    """Get secret value from Secret Manager."""
    global _sm_client
    if _sm_client is None:
        _sm_client = secretmanager.SecretManagerServiceClient()
    response = _sm_client.access_secret_version(name=secret_resource_name)
    return response.payload.data.decode("UTF-8")


def get_db_session():
    """Get database session, reusing engine across invocations."""
    global _engine, _session_factory

    if _engine is None:
        db_host = os.environ.get("DB_HOST", "localhost")
        db_port = os.environ.get("DB_PORT", "5432")
        db_name = os.environ.get("DB_NAME", "behindbars")
        db_user = os.environ.get("DB_USER", "behindbars")

        # Get password from Secret Manager using the full resource name
        db_password_secret = os.environ.get("DB_PASSWORD_SECRET", "")
        if db_password_secret:
            db_password = _get_secret(db_password_secret)
        else:
            db_password = os.environ.get("DB_PASSWORD", "")

        db_url = f"postgresql+psycopg2://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"
        _engine = create_engine(db_url, pool_pre_ping=True, pool_size=1)
        _session_factory = sessionmaker(bind=_engine)

    return _session_factory()


def download_batch_results(bucket_name: str, blob_name: str) -> list[dict]:
    """Download and parse batch job results from GCS.

    The blob_name is the specific file that triggered the function.
    We need to find all .jsonl files in the same output directory.
    """
    client = storage.Client()
    bucket = client.bucket(bucket_name)

    # Extract the output directory from the blob name
    # e.g., batch_jobs/2026-02-03/output/predictions.jsonl -> batch_jobs/2026-02-03/output/
    output_dir = "/".join(blob_name.split("/")[:-1]) + "/"

    results = []
    blobs = bucket.list_blobs(prefix=output_dir)

    for blob in blobs:
        if blob.name.endswith(".jsonl"):
            content = blob.download_as_text()
            for line in content.strip().split("\n"):
                if line:
                    results.append(json.loads(line))

    print(f"Downloaded {len(results)} batch results from gs://{bucket_name}/{output_dir}")
    return results


def parse_batch_results(results: list[dict]) -> tuple[dict | None, list[dict] | None]:
    """Parse batch results into newsletter components.

    Returns:
        Tuple of (newsletter_content dict, press_review list).
    """
    newsletter_content = None
    press_review = None

    for result in results:
        custom_id = result.get("custom_id", "")
        response = result.get("response", {})

        # Extract text from response
        candidates = response.get("candidates", [])
        if not candidates:
            print(f"Empty response for {custom_id}")
            continue

        content = candidates[0].get("content", {})
        parts = content.get("parts", [])
        if not parts:
            continue

        text = parts[0].get("text", "")
        if not text:
            continue

        try:
            parsed = json.loads(text)

            if custom_id.startswith("newsletter_content"):
                newsletter_content = parsed
                print(f"Parsed newsletter content: {parsed.get('title', '')[:50]}")

            elif custom_id.startswith("press_review"):
                press_review = parsed
                print(f"Parsed press review: {len(parsed)} categories")

        except (json.JSONDecodeError, TypeError) as e:
            print(f"Parse error for {custom_id}: {e}")

    return newsletter_content, press_review


def render_newsletter_html(
    newsletter_content: dict,
    press_review: list[dict],
    issue_date: date,
) -> str:
    """Render newsletter HTML from components with proper escaping."""
    today_str = issue_date.strftime("%d.%m.%Y")

    # Escape all content to prevent XSS
    title = html.escape(newsletter_content.get("title", "BehindBars"))
    subtitle = html.escape(newsletter_content.get("subtitle", ""))
    opening = html.escape(newsletter_content.get("opening", ""))
    closing = html.escape(newsletter_content.get("closing", ""))

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='it'>",
        "<head>",
        "<meta charset='UTF-8'>",
        f"<title>BehindBars - {today_str}</title>",
        "<style>",
        "body { font-family: Georgia, serif; max-width: 800px; margin: 0 auto; padding: 20px; }",
        "h1 { color: #1a1a2e; }",
        "h2 { color: #16213e; }",
        ".category { margin-bottom: 30px; }",
        ".article { margin-left: 20px; margin-bottom: 15px; }",
        ".article-title { font-weight: bold; }",
        ".comment { font-style: italic; color: #444; margin: 10px 0; }",
        "</style>",
        "</head>",
        "<body>",
        f"<h1>{title}</h1>",
        f"<h2>{subtitle}</h2>",
        f"<p>{opening}</p>",
        "<hr>",
    ]

    # Press review categories
    for category in press_review or []:
        cat_name = html.escape(category.get("category", ""))
        cat_comment = html.escape(category.get("comment", ""))

        html_parts.append("<div class='category'>")
        html_parts.append(f"<h3>{cat_name}</h3>")
        html_parts.append(f"<p class='comment'>{cat_comment}</p>")

        for article in category.get("articles", []):
            art_title = html.escape(article.get("title", ""))
            art_link = html.escape(article.get("link", "#"))

            html_parts.append("<div class='article'>")
            html_parts.append(
                f"<a href='{art_link}' class='article-title'>{art_title}</a>"
            )
            html_parts.append("</div>")

        html_parts.append("</div>")

    html_parts.extend(
        [
            "<hr>",
            f"<p>{closing}</p>",
            "</body>",
            "</html>",
        ]
    )

    return "\n".join(html_parts)


def render_newsletter_txt(
    newsletter_content: dict,
    press_review: list[dict],
    issue_date: date,
) -> str:
    """Render newsletter plain text from components."""
    today_str = issue_date.strftime("%d.%m.%Y")

    lines = [
        f"BEHINDBARS - {today_str}",
        "=" * 60,
        "",
        newsletter_content.get("title", ""),
        newsletter_content.get("subtitle", ""),
        "",
        newsletter_content.get("opening", ""),
        "",
        "-" * 60,
        "",
    ]

    for category in press_review or []:
        lines.append(f"### {category.get('category', '')}")
        lines.append("")
        lines.append(category.get("comment", ""))
        lines.append("")

        for article in category.get("articles", []):
            lines.append(f"  - {article.get('title', '')}")
            lines.append(f"    {article.get('link', '')}")

        lines.append("")

    lines.extend(
        [
            "-" * 60,
            "",
            newsletter_content.get("closing", ""),
        ]
    )

    return "\n".join(lines)


def upload_to_gcs(bucket_name: str, blob_path: str, content: str) -> str:
    """Upload content to GCS and return the URI."""
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(content)
    return f"gs://{bucket_name}/{blob_path}"


def extract_issue_date_from_path(blob_name: str) -> date:
    """Extract issue date from batch output path.

    Expected format: batch_jobs/2026-01-30/output/predictions.jsonl
    """
    match = re.search(r"batch_jobs/(\d{4}-\d{2}-\d{2})/", blob_name)
    if match:
        return date.fromisoformat(match.group(1))
    return date.today()


@functions_framework.cloud_event
def process_batch_results(cloud_event: CloudEvent):
    """Process completed Vertex AI batch job.

    Triggered by GCS Object Finalize when batch output file is created.
    Downloads results, renders newsletter, saves to DB and GCS.
    """
    print(f"Received event: {cloud_event.data}")

    # Extract GCS object info from event
    event_data = cloud_event.data
    bucket_name = event_data.get("bucket", "")
    blob_name = event_data.get("name", "")

    print(f"Processing: gs://{bucket_name}/{blob_name}")

    # Only process .jsonl files in batch output directories
    if not blob_name.endswith(".jsonl") or "/output/" not in blob_name:
        print(f"Skipping non-output file: {blob_name}")
        return

    # Extract issue date from path
    issue_date = extract_issue_date_from_path(blob_name)
    print(f"Issue date: {issue_date}")

    # Download and parse results
    results = download_batch_results(bucket_name, blob_name)
    if not results:
        print("No results found")
        return

    newsletter_content, press_review = parse_batch_results(results)

    if not newsletter_content:
        print("No newsletter content found in results")
        return

    # Render HTML and TXT
    html_content = render_newsletter_html(newsletter_content, press_review, issue_date)
    txt_content = render_newsletter_txt(newsletter_content, press_review, issue_date)

    print(f"Rendered newsletter: {len(html_content)} chars HTML, {len(txt_content)} chars TXT")

    # Upload to GCS
    gcs_bucket = os.environ.get("GCS_BUCKET")
    if gcs_bucket:
        date_str = issue_date.strftime("%Y%m%d")
        html_uri = upload_to_gcs(
            gcs_bucket,
            f"previous_issues/{date_str}_issue.html",
            html_content,
        )
        txt_uri = upload_to_gcs(
            gcs_bucket,
            f"previous_issues/{date_str}_issue.txt",
            txt_content,
        )
        print(f"Uploaded to GCS: {html_uri}, {txt_uri}")

    # Save to database
    session = get_db_session()
    try:
        # Delete existing newsletter for this date
        session.execute(delete(Newsletter).where(Newsletter.issue_date == issue_date))

        # Create new newsletter
        newsletter = Newsletter(
            issue_date=issue_date,
            title=newsletter_content.get("title", ""),
            subtitle=newsletter_content.get("subtitle", ""),
            opening=newsletter_content.get("opening", ""),
            closing=newsletter_content.get("closing", ""),
            html_content=html_content,
            txt_content=txt_content,
            press_review=press_review,
        )
        session.add(newsletter)
        session.commit()
        print(f"Saved newsletter to database: {issue_date}")

    except Exception as e:
        print(f"Database error: {e}")
        session.rollback()
        raise

    finally:
        session.close()

    print(f"Successfully processed batch job for {issue_date}")
