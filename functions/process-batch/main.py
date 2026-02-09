# ABOUTME: Cloud Function to process Vertex AI batch job results.
# ABOUTME: Triggered by GCS Object Finalize when batch output is written.

import contextlib
import html
import json
import os
import re
import uuid
from datetime import UTC, date, datetime, timedelta

import functions_framework
from cloudevents.http import CloudEvent
from google.cloud import secretmanager, storage
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    create_engine,
    delete,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import declarative_base, sessionmaker
from vertexai.language_models import TextEmbeddingInput, TextEmbeddingModel

# Database setup - global scope for connection reuse across invocations
Base = declarative_base()


# ORM models are intentionally duplicated from src/behind_bars_pulse/db/models.py.
# Cloud Functions deploy as standalone packages without the main app source tree.
# Schema changes in the main app MUST be reflected here manually.


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
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class Article(Base):
    """Article model for database storage."""

    __tablename__ = "articles"

    id = Column(Integer, primary_key=True)
    title = Column(String(500), nullable=False)
    link = Column(String(2000), unique=True, nullable=False, index=True)
    content = Column(Text)
    author = Column(String(200))
    source = Column(String(200))
    summary = Column(Text)
    published_date = Column(Date)
    embedding = Column(Vector(768))
    created_at = Column(DateTime, nullable=False, server_default=func.now())


class PrisonEvent(Base):
    """Prison event model for database storage."""

    __tablename__ = "prison_events"

    id = Column(Integer, primary_key=True)
    event_type = Column(String(50), nullable=False, index=True)
    event_date = Column(Date, index=True)
    facility = Column(String(300))
    region = Column(String(100))
    count = Column(Integer)
    description = Column(Text)
    source_url = Column(String(2000))
    article_id = Column(Integer, ForeignKey("articles.id"))
    confidence = Column(Float, default=1.0)
    is_aggregate = Column(Boolean, default=False)
    extracted_at = Column(DateTime, nullable=False, server_default=func.now())


class FacilitySnapshot(Base):
    """Facility capacity snapshot model for database storage."""

    __tablename__ = "facility_snapshots"

    id = Column(Integer, primary_key=True)
    facility = Column(String(300), nullable=False, index=True)
    region = Column(String(100))
    snapshot_date = Column(Date, nullable=False, index=True)
    inmates = Column(Integer)
    capacity = Column(Integer)
    occupancy_rate = Column(Float)
    source_url = Column(String(2000))
    article_id = Column(Integer, ForeignKey("articles.id"))
    extracted_at = Column(DateTime, nullable=False, server_default=func.now())


# Global engine for connection reuse (warm starts)
_engine = None
_session_factory = None
_sm_client = None
_storage_client = None

# Facility alias mappings for normalization (subset of main app's mappings)
FACILITY_ALIASES = {
    "Canton Mombello (Brescia)": [
        "brescia canton mombello",
        "canton mombello",
        "brescia - canton mombello",
    ],
    "Sollicciano (Firenze)": ["sollicciano", "firenze sollicciano"],
    "Poggioreale (Napoli)": ["poggioreale", "napoli poggioreale"],
    "Regina Coeli (Roma)": ["regina coeli", "roma regina coeli"],
    "San Vittore (Milano)": ["san vittore", "milano san vittore"],
    "Rebibbia (Roma)": ["rebibbia", "roma rebibbia"],
    "Marassi (Genova)": ["marassi", "genova marassi"],
}

# Build reverse lookup
_ALIAS_MAP = {}
for canonical, aliases in FACILITY_ALIASES.items():
    for alias in aliases:
        _ALIAS_MAP[alias] = canonical


def normalize_facility_name(name: str | None) -> str | None:
    """Normalize facility name using alias mappings."""
    if not name:
        return name
    lower = name.strip().lower()
    return _ALIAS_MAP.get(lower, name.strip())


# Region mappings for common facilities
FACILITY_REGIONS = {
    "Canton Mombello (Brescia)": "Lombardia",
    "Sollicciano (Firenze)": "Toscana",
    "Poggioreale (Napoli)": "Campania",
    "Regina Coeli (Roma)": "Lazio",
    "San Vittore (Milano)": "Lombardia",
    "Rebibbia (Roma)": "Lazio",
    "Marassi (Genova)": "Liguria",
}


def get_facility_region(facility: str | None) -> str | None:
    """Get region for a facility name."""
    if not facility:
        return None
    return FACILITY_REGIONS.get(facility)


def _get_secret(secret_resource_name: str) -> str:
    """Get secret value from Secret Manager."""
    global _sm_client
    if _sm_client is None:
        _sm_client = secretmanager.SecretManagerServiceClient()
    response = _sm_client.access_secret_version(name=secret_resource_name)
    return response.payload.data.decode("UTF-8")


def _get_storage_client() -> storage.Client:
    """Get GCS storage client, reusing across invocations."""
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()
    return _storage_client


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
    client = _get_storage_client()
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


def is_collector_batch(blob_name: str) -> bool:
    """Check if this batch output is from a collector job.

    Collector batches live under batch_jobs/collect/{date}/output/
    Newsletter batches live under batch_jobs/{date}/output/
    """
    return "/collect/" in blob_name


def extract_text_from_result(result: dict) -> str | None:
    """Extract text content from a single batch result entry."""
    response = result.get("response", {})
    candidates = response.get("candidates", [])
    if not candidates:
        return None
    content = candidates[0].get("content", {})
    parts = content.get("parts", [])
    if not parts:
        return None
    text = parts[0].get("text", "")
    return text if text else None


def parse_batch_results(results: list[dict]) -> tuple[dict | None, list[dict] | None]:
    """Parse batch results into newsletter components.

    Returns:
        Tuple of (newsletter_content dict, press_review list).
    """
    newsletter_content = None
    press_review = None

    for result in results:
        custom_id = result.get("custom_id", "")
        text = extract_text_from_result(result)
        if not text:
            print(f"Empty response for {custom_id}")
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


def parse_collector_batch_results(results: list[dict]) -> dict:
    """Parse collector batch results into structured components.

    Args:
        results: List of result dicts from download_batch_results.

    Returns:
        Dictionary with enrichments, stories, entities, followups, events, capacity.
    """
    parsed = {
        "enrichments": {},
        "stories": {"updated_stories": [], "new_stories": []},
        "entities": {"updated_characters": [], "new_characters": []},
        "followups": {"followups": []},
        "events": {"events": []},
        "capacity": {"snapshots": []},
    }

    for result in results:
        custom_id = result.get("custom_id", "")
        text = extract_text_from_result(result)
        if not text:
            print(f"Empty response for collector batch: {custom_id}")
            continue

        try:
            data = json.loads(text)

            if custom_id.startswith("enrich_article_"):
                url_hash = custom_id[len("enrich_article_") :]
                if isinstance(data, list) and data:
                    parsed["enrichments"][url_hash] = data[0]
                else:
                    parsed["enrichments"][url_hash] = data
                print(f"Parsed enrichment for {url_hash}")

            elif custom_id.startswith("extract_stories_"):
                parsed["stories"] = data
                print(
                    f"Parsed stories: {len(data.get('updated_stories', []))} updated, "
                    f"{len(data.get('new_stories', []))} new"
                )

            elif custom_id.startswith("extract_entities_"):
                parsed["entities"] = data
                print(
                    f"Parsed entities: {len(data.get('updated_characters', []))} updated, "
                    f"{len(data.get('new_characters', []))} new"
                )

            elif custom_id.startswith("detect_followups_"):
                parsed["followups"] = data
                print(f"Parsed followups: {len(data.get('followups', []))}")

            elif custom_id.startswith("extract_events_"):
                parsed["events"] = data
                print(f"Parsed events: {len(data.get('events', []))}")

            elif custom_id.startswith("extract_capacity_"):
                parsed["capacity"] = data
                print(f"Parsed capacity: {len(data.get('snapshots', []))}")

        except (json.JSONDecodeError, TypeError) as e:
            print(f"Parse error for collector {custom_id}: {e}")

    return parsed


def download_raw_articles(bucket_name: str, collection_date: date) -> dict:
    """Download raw articles JSON from GCS.

    Args:
        bucket_name: GCS bucket name.
        collection_date: Date of collection.

    Returns:
        Dictionary of URL -> article data dict.
    """
    client = _get_storage_client()
    bucket = client.bucket(bucket_name)
    blob_path = f"batch_jobs/collect/{collection_date.isoformat()}/raw_articles.json"
    blob = bucket.blob(blob_path)

    if not blob.exists():
        print(f"Raw articles not found: gs://{bucket_name}/{blob_path}")
        return {}

    content = blob.download_as_text()
    articles = json.loads(content)
    print(f"Downloaded {len(articles)} raw articles from GCS")
    return articles


def load_narrative_context_from_gcs(bucket_name: str) -> dict:
    """Load narrative context JSON from GCS.

    Args:
        bucket_name: GCS bucket name.

    Returns:
        Narrative context dict, or empty structure if not found.

    Note: This performs a Read-Modify-Write on GCS which is not atomic.
    Acceptable because collector batch runs at most once per day (no concurrency).
    """
    client = _get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob("data/narrative_context.json")

    if not blob.exists():
        print("Narrative context not found on GCS, starting fresh")
        return {
            "ongoing_storylines": [],
            "key_characters": [],
            "editorial_tone": "Riflessivo e professionale",
            "pending_followups": [],
        }

    content = blob.download_as_text()
    context = json.loads(content)
    print(
        f"Loaded narrative context: {len(context.get('ongoing_storylines', []))} stories, "
        f"{len(context.get('key_characters', []))} characters"
    )
    return context


def save_narrative_context_to_gcs(bucket_name: str, context: dict) -> None:
    """Save narrative context JSON to GCS.

    Args:
        bucket_name: GCS bucket name.
        context: Narrative context dict to save.
    """
    client = _get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob("data/narrative_context.json")

    context["last_updated"] = datetime.now(UTC).isoformat()
    content = json.dumps(context, indent=2, ensure_ascii=False, default=str)
    blob.upload_from_string(content, content_type="application/json")
    print("Saved narrative context to GCS")


def update_narrative_context(
    context: dict,
    stories_result: dict,
    entities_result: dict,
    followups_result: dict,
    collection_date: date,
) -> dict:
    """Update narrative context with extraction results.

    Args:
        context: Existing narrative context dict.
        stories_result: Parsed stories extraction.
        entities_result: Parsed entities extraction.
        followups_result: Parsed followups extraction.
        collection_date: Date of collection.

    Returns:
        Updated narrative context dict.
    """
    date_str = collection_date.isoformat()

    # Update existing stories
    story_map = {s["id"]: s for s in context.get("ongoing_storylines", []) if "id" in s}
    for update in stories_result.get("updated_stories", []):
        story_id = update.get("id", "")
        if story_id in story_map:
            story = story_map[story_id]
            story["summary"] = update.get("new_summary", story.get("summary", ""))
            story["keywords"] = list(
                set(story.get("keywords", []) + update.get("new_keywords", []))
            )
            story["impact_score"] = float(
                update.get("impact_score", story.get("impact_score", 0.5))
            )
            story["last_update"] = date_str
            story["mention_count"] = story.get("mention_count", 1) + 1
            for url in update.get("article_urls", []):
                if url not in story.get("related_articles", []):
                    story.setdefault("related_articles", []).append(url)
            print(f"Updated story: {story.get('topic', '')}")

    # Add new stories
    for new_story in stories_result.get("new_stories", []):
        story = {
            "id": str(uuid.uuid4()),
            "topic": new_story.get("topic", "Unknown"),
            "status": "active",
            "first_seen": date_str,
            "last_update": date_str,
            "summary": new_story.get("summary", ""),
            "keywords": new_story.get("keywords", []),
            "related_articles": new_story.get("article_urls", []),
            "mention_count": 1,
            "impact_score": float(new_story.get("impact_score", 0.5)),
            "weekly_highlight": False,
        }
        context.setdefault("ongoing_storylines", []).append(story)
        print(f"New story: {story['topic']}")

    # Update existing characters
    char_map = {c["name"].lower(): c for c in context.get("key_characters", [])}
    for update in entities_result.get("updated_characters", []):
        name_lower = update.get("name", "").lower()
        if name_lower in char_map:
            char = char_map[name_lower]
            if update.get("new_position"):
                pos = update["new_position"]
                char.setdefault("positions", []).append(
                    {
                        "date": date_str,
                        "stance": pos.get("stance", ""),
                        "source_url": pos.get("source_url"),
                    }
                )
                print(f"Updated character: {char.get('name', '')}")

    # Add new characters
    for new_char in entities_result.get("new_characters", []):
        positions = []
        if new_char.get("initial_position"):
            pos = new_char["initial_position"]
            positions.append(
                {
                    "date": date_str,
                    "stance": pos.get("stance", ""),
                    "source_url": pos.get("source_url"),
                }
            )
        char = {
            "name": new_char.get("name", "Unknown"),
            "role": new_char.get("role", ""),
            "aliases": new_char.get("aliases", []),
            "positions": positions,
        }
        context.setdefault("key_characters", []).append(char)
        print(f"New character: {char['name']}")

    # Add follow-ups
    for fu_data in followups_result.get("followups", []):
        expected_date = fu_data.get("expected_date", "")
        try:
            date.fromisoformat(expected_date)
        except (ValueError, TypeError):
            print(f"Invalid followup date: {expected_date}")
            continue

        followup = {
            "id": str(uuid.uuid4()),
            "event": fu_data.get("event", "Unknown event"),
            "expected_date": expected_date,
            "story_id": fu_data.get("story_id"),
            "created_at": date_str,
            "resolved": False,
        }
        context.setdefault("pending_followups", []).append(followup)
        print(f"New followup: {followup['event']}")

    # Archive old stories (>90 days without update)
    cutoff = (collection_date - timedelta(days=90)).isoformat()
    for story in context.get("ongoing_storylines", []):
        if story.get("status") == "active" and story.get("last_update", "") < cutoff:
            story["status"] = "dormant"
            print(f"Archived dormant story: {story.get('topic', '')}")

    return context


def generate_article_embeddings(texts: list[str]) -> list[list[float] | None]:
    """Generate embeddings for multiple texts in batch using Vertex AI.

    Uses gemini-embedding-001 with RETRIEVAL_DOCUMENT task type, 768 dimensions.
    Returns list of embeddings (or None for failed items) in same order as input.
    """
    if not texts:
        return []
    try:
        model = TextEmbeddingModel.from_pretrained("gemini-embedding-001")
        inputs = [TextEmbeddingInput(t, "RETRIEVAL_DOCUMENT") for t in texts]
        results = model.get_embeddings(inputs, output_dimensionality=768)
        return [r.values for r in results]
    except Exception as e:
        print(f"Batch embedding generation failed: {e}")
        return [None] * len(texts)


def save_enriched_articles_to_db(
    session,
    raw_articles: dict,
    enrichments: dict,
    collection_date: date,
) -> dict[str, int]:
    """Save enriched articles to database.

    Args:
        session: SQLAlchemy session.
        raw_articles: Dict of URL -> raw article data from GCS.
        enrichments: Dict of url_hash -> enrichment data from batch results.
        collection_date: Date of collection.

    Returns:
        Mapping of article URL -> database article ID.
    """
    url_to_id: dict[str, int] = {}
    saved = 0
    skipped = 0

    # Build hash->url reverse mapping
    hash_to_url = {}
    for url in raw_articles:
        url_hash = uuid.uuid5(uuid.NAMESPACE_URL, url).hex[:12]
        hash_to_url[url_hash] = url

    # Batch-fetch existing articles to avoid N+1 queries
    all_urls = [hash_to_url[h] for h in enrichments if h in hash_to_url]
    existing_articles = {}
    if all_urls:
        rows = session.execute(
            select(Article.id, Article.link).where(Article.link.in_(all_urls))
        ).all()
        existing_articles = {link: aid for aid, link in rows}

    # First pass: collect new articles and their embed texts
    articles_to_save = []
    for url_hash, enrichment in enrichments.items():
        url = hash_to_url.get(url_hash)
        if not url:
            print(f"No URL found for hash {url_hash}, skipping")
            continue

        raw = raw_articles.get(url, {})

        # Check if article already exists (from batch-fetched set)
        if url in existing_articles:
            url_to_id[url] = existing_articles[url]
            skipped += 1
            continue

        # Parse published_date
        published_date = collection_date
        raw_date = raw.get("published_date")
        if raw_date:
            with contextlib.suppress(ValueError, TypeError):
                published_date = date.fromisoformat(raw_date)

        # Build embedding text
        embed_text = raw.get("title", "")
        if enrichment.get("summary"):
            embed_text = f"{embed_text}. {enrichment['summary']}"

        articles_to_save.append((url, raw, enrichment, published_date, embed_text))

    # Batch-embed all new articles at once
    embed_texts = [a[4] for a in articles_to_save]
    embeddings = generate_article_embeddings(embed_texts)

    # Second pass: create and save articles with embeddings
    for i, (url, raw, enrichment, published_date, _) in enumerate(articles_to_save):
        db_article = Article(
            title=raw.get("title", ""),
            link=url,
            content=raw.get("content", ""),
            author=enrichment.get("author"),
            source=enrichment.get("source"),
            summary=enrichment.get("summary"),
            published_date=published_date,
            embedding=embeddings[i] if i < len(embeddings) else None,
        )
        session.add(db_article)
        session.flush()
        url_to_id[url] = db_article.id
        saved += 1

    print(f"Articles saved: {saved}, skipped: {skipped}")
    return url_to_id


def save_prison_events_to_db(
    session,
    events: list[dict],
    url_to_id: dict[str, int],
) -> int:
    """Save extracted prison events to database with deduplication.

    Args:
        session: SQLAlchemy session.
        events: List of event dicts from AI extraction.
        url_to_id: Mapping of article URLs to DB article IDs.

    Returns:
        Number of events saved.
    """
    saved = 0
    skipped = 0

    # Batch-fetch recent events for dedup (avoids N+1 queries)
    # Collect all dates from incoming events for targeted fetch
    incoming_dates = set()
    for ev in events:
        if ev.get("event_date"):
            with contextlib.suppress(ValueError):
                incoming_dates.add(date.fromisoformat(ev["event_date"]))

    existing_events_by_key: set[tuple] = set()
    existing_exact: set[tuple] = set()

    # Fetch by matching dates (covers dated events)
    if incoming_dates:
        db_events = (
            session.execute(
                select(PrisonEvent).where(
                    PrisonEvent.event_date.in_(list(incoming_dates)),
                    PrisonEvent.facility.isnot(None),
                )
            )
            .scalars()
            .all()
        )
        for m in db_events:
            norm = normalize_facility_name(m.facility)
            existing_events_by_key.add((str(m.event_date), m.event_type, norm))
            existing_exact.add((m.source_url, m.event_type, str(m.event_date), m.facility))

    # Also fetch by source_url to catch dateless duplicates
    incoming_urls = {ev.get("source_url", "") for ev in events if ev.get("source_url")}
    if incoming_urls:
        url_events = (
            session.execute(
                select(PrisonEvent).where(PrisonEvent.source_url.in_(list(incoming_urls)))
            )
            .scalars()
            .all()
        )
        for m in url_events:
            norm = normalize_facility_name(m.facility) if m.facility else m.facility
            existing_exact.add((m.source_url, m.event_type, str(m.event_date), norm))

    for event_data in events:
        source_url = event_data.get("source_url", "")
        event_type = event_data.get("event_type", "unknown")

        raw_facility = event_data.get("facility")
        facility = normalize_facility_name(raw_facility)

        region = event_data.get("region")
        if not region and facility:
            region = get_facility_region(facility)

        event_date = None
        if event_data.get("event_date"):
            with contextlib.suppress(ValueError):
                event_date = date.fromisoformat(event_data["event_date"])

        # Dedup: check (date + type + normalized facility) against batch-fetched set
        if event_date and facility:
            key = (str(event_date), event_type, facility)
            if key in existing_events_by_key:
                skipped += 1
                continue

        # Exact match dedup against batch-fetched set
        exact_key = (source_url, event_type, str(event_date), facility)
        if exact_key in existing_exact:
            skipped += 1
            continue

        article_id = url_to_id.get(source_url)
        is_aggregate = event_data.get("is_aggregate", False)

        event = PrisonEvent(
            event_type=event_type,
            event_date=event_date,
            facility=facility,
            region=region,
            count=event_data.get("count"),
            description=event_data.get("description", ""),
            source_url=source_url,
            article_id=article_id,
            confidence=float(event_data.get("confidence", 1.0)),
            is_aggregate=is_aggregate,
            extracted_at=datetime.now(UTC),
        )
        session.add(event)
        saved += 1

    print(f"Events saved: {saved}, skipped: {skipped}")
    return saved


def save_capacity_snapshots_to_db(
    session,
    snapshots: list[dict],
    url_to_id: dict[str, int],
) -> int:
    """Save facility capacity snapshots to database with deduplication.

    Args:
        session: SQLAlchemy session.
        snapshots: List of snapshot dicts from AI extraction.
        url_to_id: Mapping of article URLs to DB article IDs.

    Returns:
        Number of snapshots saved.
    """
    saved = 0
    skipped = 0

    for snap_data in snapshots:
        source_url = snap_data.get("source_url", "")

        raw_facility = snap_data.get("facility", "")
        facility = normalize_facility_name(raw_facility) or raw_facility

        region = snap_data.get("region")
        if not region and facility:
            region = get_facility_region(facility)

        snapshot_date = None
        if snap_data.get("snapshot_date"):
            try:
                snapshot_date = date.fromisoformat(snap_data["snapshot_date"])
            except ValueError:
                continue

        if not snapshot_date:
            continue

        # Dedup
        existing = session.execute(
            select(FacilitySnapshot).where(
                FacilitySnapshot.facility == facility,
                FacilitySnapshot.snapshot_date == snapshot_date,
                FacilitySnapshot.source_url == source_url,
            )
        ).scalar_one_or_none()

        if existing:
            skipped += 1
            continue

        article_id = url_to_id.get(source_url)

        snapshot = FacilitySnapshot(
            facility=facility,
            region=region,
            snapshot_date=snapshot_date,
            inmates=snap_data.get("inmates"),
            capacity=snap_data.get("capacity"),
            occupancy_rate=snap_data.get("occupancy_rate"),
            source_url=source_url,
            article_id=article_id,
            extracted_at=datetime.now(UTC),
        )
        session.add(snapshot)
        saved += 1

    print(f"Capacity snapshots saved: {saved}, skipped: {skipped}")
    return saved


def process_collector_results(bucket_name: str, blob_name: str, collection_date: date) -> None:
    """Process collector batch results: enrich articles, update narrative, save events.

    Args:
        bucket_name: GCS bucket containing batch results.
        blob_name: Blob name that triggered the function.
        collection_date: Date of the collection.
    """
    # Download batch results
    results = download_batch_results(bucket_name, blob_name)
    if not results:
        print("No collector batch results found")
        return

    # Parse results
    parsed = parse_collector_batch_results(results)

    # Download raw articles from GCS
    raw_articles = download_raw_articles(bucket_name, collection_date)
    if not raw_articles:
        print("No raw articles found, cannot proceed")
        return

    # Save enriched articles to DB
    session = get_db_session()
    try:
        url_to_id = save_enriched_articles_to_db(
            session, raw_articles, parsed["enrichments"], collection_date
        )

        # Save prison events
        events = parsed["events"].get("events", [])
        if events:
            save_prison_events_to_db(session, events, url_to_id)

        # Save capacity snapshots
        snapshots = parsed["capacity"].get("snapshots", [])
        if snapshots:
            save_capacity_snapshots_to_db(session, snapshots, url_to_id)

        session.commit()
        print(f"Database changes committed for {collection_date}")

    except Exception as e:
        print(f"Database error: {e}")
        session.rollback()
        raise
    finally:
        session.close()

    # Update narrative context on GCS
    gcs_bucket = os.environ.get("GCS_BUCKET", bucket_name)
    context = load_narrative_context_from_gcs(gcs_bucket)
    context = update_narrative_context(
        context,
        parsed["stories"],
        parsed["entities"],
        parsed["followups"],
        collection_date,
    )
    save_narrative_context_to_gcs(gcs_bucket, context)

    # Save collected articles JSON to GCS (for newsletter generation reference)
    enriched_articles = {}
    hash_to_url = {}
    for url in raw_articles:
        url_hash = uuid.uuid5(uuid.NAMESPACE_URL, url).hex[:12]
        hash_to_url[url_hash] = url

    for url_hash, enrichment in parsed["enrichments"].items():
        url = hash_to_url.get(url_hash, "")
        if not url:
            continue
        raw = raw_articles.get(url, {})
        enriched_articles[url] = {
            "title": raw.get("title", ""),
            "link": url,
            "content": raw.get("content", ""),
            "author": enrichment.get("author", ""),
            "source": enrichment.get("source", ""),
            "summary": enrichment.get("summary", ""),
            "published_date": raw.get("published_date"),
        }

    if enriched_articles:
        client = _get_storage_client()
        bucket = client.bucket(gcs_bucket)
        blob_path = f"data/collected_articles/{collection_date.isoformat()}.json"
        blob = bucket.blob(blob_path)
        blob.upload_from_string(
            json.dumps(enriched_articles, indent=2, ensure_ascii=False),
            content_type="application/json",
        )
        print(f"Saved enriched articles to GCS: {blob_path}")

    print(f"Successfully processed collector batch for {collection_date}")


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
            html_parts.append(f"<a href='{art_link}' class='article-title'>{art_title}</a>")
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
    client = _get_storage_client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_path)
    blob.upload_from_string(content)
    return f"gs://{bucket_name}/{blob_path}"


def extract_issue_date_from_path(blob_name: str) -> date:
    """Extract issue date from batch output path.

    Expected formats:
    - Newsletter: batch_jobs/2026-01-30/output/predictions.jsonl
    - Collector: batch_jobs/collect/2026-01-30/output/predictions.jsonl
    """
    match = re.search(r"batch_jobs/(?:collect/)?(\d{4}-\d{2}-\d{2})/", blob_name)
    if match:
        return date.fromisoformat(match.group(1))
    return date.today()


@functions_framework.cloud_event
def process_batch_results(cloud_event: CloudEvent):
    """Process completed Vertex AI batch job.

    Triggered by GCS Object Finalize when batch output file is created.
    Routes to newsletter or collector processing based on path.
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

    # Extract date from path
    issue_date = extract_issue_date_from_path(blob_name)
    print(f"Date: {issue_date}")

    # Route to appropriate handler
    if is_collector_batch(blob_name):
        print(f"Processing COLLECTOR batch for {issue_date}")
        process_collector_results(bucket_name, blob_name, issue_date)
        return

    # Newsletter batch processing (existing logic)
    print(f"Processing NEWSLETTER batch for {issue_date}")

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
