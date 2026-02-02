# ABOUTME: Re-extract prison events and capacity snapshots from collected articles.
# ABOUTME: One-time script to repopulate statistics with updated extraction prompts.

import asyncio
import json
from datetime import date, datetime
from pathlib import Path

import structlog

from behind_bars_pulse.ai.service import AIService
from behind_bars_pulse.config import get_settings
from behind_bars_pulse.db.models import FacilitySnapshot, PrisonEvent
from behind_bars_pulse.db.repository import FacilitySnapshotRepository, PrisonEventRepository
from behind_bars_pulse.db.session import get_session
from behind_bars_pulse.models import EnrichedArticle
from behind_bars_pulse.utils.facilities import get_facility_region, normalize_facility_name

log = structlog.get_logger()


def load_collected_articles(data_dir: Path) -> dict[str, EnrichedArticle]:
    """Load all collected articles from JSON files."""
    all_articles: dict[str, EnrichedArticle] = {}

    for json_file in sorted(data_dir.glob("*.json")):
        log.info("loading_file", file=json_file.name)
        with open(json_file) as f:
            data = json.load(f)

        for url, article_data in data.items():
            if url in all_articles:
                continue  # Skip duplicates
            all_articles[url] = EnrichedArticle(
                title=article_data.get("title", ""),
                link=url,
                content=article_data.get("content", ""),
                author=article_data.get("author") or "",
                source=article_data.get("source") or "",
                summary=article_data.get("summary") or "",
            )

    return all_articles


async def save_events(events: list[dict]) -> int:
    """Save extracted events to database."""
    saved_count = 0
    skipped_count = 0

    async with get_session() as session:
        repo = PrisonEventRepository(session)

        for event_data in events:
            source_url = event_data.get("source_url", "")
            event_type = event_data.get("event_type", "unknown")

            # Normalize facility name
            raw_facility = event_data.get("facility")
            facility = normalize_facility_name(raw_facility)

            # Infer region from facility if not provided
            region = event_data.get("region")
            if not region and facility:
                region = get_facility_region(facility)

            # Parse event date
            event_date = None
            if event_data.get("event_date"):
                try:
                    event_date = date.fromisoformat(event_data["event_date"])
                except ValueError:
                    pass

            # Check for duplicate
            if await repo.exists_by_composite_key(source_url, event_type, event_date, facility):
                skipped_count += 1
                continue

            is_aggregate = event_data.get("is_aggregate", False)

            event = PrisonEvent(
                event_type=event_type,
                event_date=event_date,
                facility=facility,
                region=region,
                count=event_data.get("count"),
                description=event_data.get("description", ""),
                source_url=source_url,
                article_id=None,
                confidence=float(event_data.get("confidence", 1.0)),
                is_aggregate=is_aggregate,
                extracted_at=datetime.utcnow(),
            )
            await repo.save(event)
            saved_count += 1

        await session.commit()

    log.info("events_saved", saved=saved_count, skipped=skipped_count)
    return saved_count


async def save_snapshots(snapshots: list[dict]) -> int:
    """Save capacity snapshots to database."""
    saved_count = 0
    skipped_count = 0

    async with get_session() as session:
        repo = FacilitySnapshotRepository(session)

        for snap_data in snapshots:
            source_url = snap_data.get("source_url", "")

            raw_facility = snap_data.get("facility")
            facility = normalize_facility_name(raw_facility)
            if not facility:
                continue

            region = snap_data.get("region")
            if not region and facility:
                region = get_facility_region(facility)

            # Parse snapshot date
            snapshot_date = None
            if snap_data.get("snapshot_date"):
                try:
                    snapshot_date = date.fromisoformat(snap_data["snapshot_date"])
                except ValueError:
                    snapshot_date = date.today()
            else:
                snapshot_date = date.today()

            # Check for duplicate
            if await repo.exists_by_key(facility, snapshot_date, source_url):
                skipped_count += 1
                continue

            snapshot = FacilitySnapshot(
                facility=facility,
                region=region,
                snapshot_date=snapshot_date,
                inmates=snap_data.get("inmates"),
                capacity=snap_data.get("capacity"),
                occupancy_rate=snap_data.get("occupancy_rate"),
                source_url=source_url,
                article_id=None,
                extracted_at=datetime.utcnow(),
            )
            await repo.save(snapshot)
            saved_count += 1

        await session.commit()

    log.info("snapshots_saved", saved=saved_count, skipped=skipped_count)
    return saved_count


def batch_dict(d: dict, batch_size: int) -> list[dict]:
    """Split a dictionary into batches."""
    items = list(d.items())
    return [dict(items[i : i + batch_size]) for i in range(0, len(items), batch_size)]


def main():
    settings = get_settings()
    data_dir = Path("data/collected_articles")
    batch_size = 50  # Process 50 articles at a time

    if not data_dir.exists():
        log.error("data_dir_not_found", path=str(data_dir))
        return

    # Load all articles
    articles = load_collected_articles(data_dir)
    log.info("articles_loaded", count=len(articles))

    if not articles:
        log.warning("no_articles_found")
        return

    # Initialize AI service
    ai_service = AIService(settings)

    # Batch articles
    batches = batch_dict(articles, batch_size)
    log.info("processing_batches", batch_count=len(batches), batch_size=batch_size)

    all_events = []
    all_snapshots = []

    for i, batch in enumerate(batches):
        log.info("processing_batch", batch_num=i + 1, total=len(batches), articles=len(batch))

        # Extract incidents
        try:
            result = ai_service.extract_prison_events(batch, existing_events=[])
            events = result.get("events", [])
            all_events.extend(events)
            log.info("batch_incidents", batch_num=i + 1, count=len(events))
        except Exception as e:
            log.warning("batch_incident_failed", batch_num=i + 1, error=str(e))

        # Extract capacity snapshots
        try:
            result = ai_service.extract_capacity_snapshots(batch)
            snapshots = result.get("snapshots", [])
            all_snapshots.extend(snapshots)
            log.info("batch_capacity", batch_num=i + 1, count=len(snapshots))
        except Exception as e:
            log.warning("batch_capacity_failed", batch_num=i + 1, error=str(e))

    # Save all in a single async context
    async def save_all():
        events_saved = 0
        snapshots_saved = 0

        if all_events:
            events_saved = await save_events(all_events)

        if all_snapshots:
            snapshots_saved = await save_snapshots(all_snapshots)

        return events_saved, snapshots_saved

    log.info("saving_all_data", events=len(all_events), snapshots=len(all_snapshots))
    events_saved, snapshots_saved = asyncio.run(save_all())
    log.info("incidents_saved", count=events_saved)
    log.info("capacity_saved", count=snapshots_saved)

    log.info("reextraction_complete", events=len(all_events), snapshots=len(all_snapshots))


if __name__ == "__main__":
    main()
