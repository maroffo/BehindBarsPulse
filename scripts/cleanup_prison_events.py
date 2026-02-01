#!/usr/bin/env python3
# ABOUTME: One-time script to clean up prison_events table.
# ABOUTME: Normalizes facility names, marks aggregates, and removes duplicates.

"""
Cleanup script for prison_events table.

Run with:
    DB_HOST=localhost DB_PASSWORD=behindbars_local uv run python scripts/cleanup_prison_events.py
"""

import asyncio
import re

from sqlalchemy import select, update

from behind_bars_pulse.db.models import PrisonEvent
from behind_bars_pulse.db.session import get_session
from behind_bars_pulse.utils.facilities import get_facility_region, normalize_facility_name


def is_aggregate_event(event: PrisonEvent) -> bool:
    """Detect if an event is an aggregate statistic."""
    desc = (event.description or "").lower()

    # Patterns that indicate aggregate statistics
    aggregate_patterns = [
        r"statistich[ea]",
        r"dall'inizio dell'anno",
        r"dall'inizio del \d{4}",
        r"nel corso del \d{4}",
        r"totale di \d+",
        r"complessivamente \d+",
        r"\d+ suicidi nel \d{4}",
        r"\d+ morti nel \d{4}",
        r"bilancio.*anno",
    ]

    for pattern in aggregate_patterns:
        if re.search(pattern, desc):
            return True

    # Also check: count > 1 with date on Jan 1st or annual reference
    if event.count and event.count > 3:
        if event.event_date and event.event_date.day == 1 and event.event_date.month == 1:
            return True

    return False


def extract_victim_identifier(event: PrisonEvent) -> str | None:
    """Extract unique victim identifier for deduplication.

    Returns None if no identifiable victim info.
    """
    desc = (event.description or "").lower()

    # Look for name patterns
    name_match = re.search(
        r"(detenuto|uomo|donna|persona)\s+(?:di\s+)?(?:nome\s+)?([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)",
        event.description or "",
        re.IGNORECASE,
    )
    if name_match:
        name = name_match.group(2).lower()
        # Combine with age if present
        age_match = re.search(r"(\d{2,3})\s*anni", desc)
        if age_match:
            return f"{name}_{age_match.group(1)}"
        return name

    # Look for age + facility combo (less precise but helpful)
    age_match = re.search(r"(\d{2})\s*anni", desc)
    if age_match and event.event_date and event.facility:
        return f"{event.event_date}_{event.facility}_{age_match.group(1)}"

    return None


async def cleanup():
    """Main cleanup function."""
    print("Starting cleanup...")

    async with get_session() as session:
        # Get all events
        result = await session.execute(select(PrisonEvent).order_by(PrisonEvent.id))
        events = list(result.scalars().all())
        print(f"Found {len(events)} events")

        # Track changes
        normalized_count = 0
        aggregates_marked = 0
        duplicates_removed = 0
        regions_inferred = 0

        # Track seen events for deduplication
        seen_victims: dict[str, int] = {}  # victim_id -> event_id

        for event in events:
            changes = False

            # 1. Normalize facility name
            if event.facility:
                normalized = normalize_facility_name(event.facility)
                if normalized != event.facility:
                    print(f"  Facility: '{event.facility}' -> '{normalized}'")
                    event.facility = normalized
                    normalized_count += 1
                    changes = True

            # 2. Infer region if missing
            if not event.region and event.facility:
                region = get_facility_region(event.facility)
                if region:
                    print(f"  Region inferred: {event.facility} -> {region}")
                    event.region = region
                    regions_inferred += 1
                    changes = True

            # 3. Mark aggregates
            if is_aggregate_event(event) and not event.is_aggregate:
                print(f"  Marking as aggregate: {event.description[:60]}...")
                event.is_aggregate = True
                aggregates_marked += 1
                changes = True

            # 4. Check for duplicates (same victim in multiple articles)
            if event.event_type == "suicide" and not event.is_aggregate:
                victim_id = extract_victim_identifier(event)
                if victim_id:
                    if victim_id in seen_victims:
                        # This is a duplicate - delete it
                        print(
                            f"  Duplicate found: {victim_id} (keeping event {seen_victims[victim_id]}, removing {event.id})"
                        )
                        await session.delete(event)
                        duplicates_removed += 1
                        continue  # Don't add to session
                    else:
                        seen_victims[victim_id] = event.id

            if changes:
                session.add(event)

        await session.commit()

        print("\n=== Cleanup Summary ===")
        print(f"Facilities normalized: {normalized_count}")
        print(f"Regions inferred: {regions_inferred}")
        print(f"Aggregates marked: {aggregates_marked}")
        print(f"Duplicates removed: {duplicates_removed}")


if __name__ == "__main__":
    asyncio.run(cleanup())
