# ABOUTME: Script to clean up prison_events data quality issues.
# ABOUTME: Removes aggregates and deduplicates events by date/facility/type.

"""
Cleanup Prison Events Data

This script fixes two data quality issues:
1. Aggregate statistics stored as events (e.g., "80 suicides in 2025" with count=80)
2. Duplicate events from the same incident reported by multiple articles

Usage:
    # Dry run - show what would change
    uv run python scripts/cleanup_prison_events.py --dry-run

    # Apply changes
    uv run python scripts/cleanup_prison_events.py

    # Via API endpoint in production
    curl -X POST "https://behindbars.news/api/cleanup-events?admin_token=YOUR_TOKEN&dry_run=false"
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


def cleanup_events(dry_run: bool = True) -> dict:
    """Clean up prison_events table.

    Args:
        dry_run: If True, only analyze without making changes.

    Returns:
        Dictionary with cleanup results.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    from behind_bars_pulse.config import get_settings
    from behind_bars_pulse.utils.facilities import normalize_facility_name

    settings = get_settings()
    if not settings.database_url:
        print("ERROR: No database URL configured")
        return {"error": "No database URL"}

    sync_url = settings.database_url_sync
    engine = create_engine(sync_url)

    results = {
        "aggregates_marked": 0,
        "duplicates_removed": 0,
        "before_count": 0,
        "after_count": 0,
        "dry_run": dry_run,
    }

    with Session(engine) as session:
        # Get all events (include is_aggregate flag)
        events = session.execute(
            text("""
                SELECT id, event_date, facility, event_type, count, description, article_id, is_aggregate
                FROM prison_events
                ORDER BY event_date, facility, event_type, id
            """)
        ).fetchall()

        results["before_count"] = len(events)
        print(f"Total events before cleanup: {len(events)}")

        # Step 1: Mark aggregate statistics (don't delete, just flag them)
        # These are events with facility=NULL and count > 1, not already marked
        print("\n=== Step 1: Marking unmarked aggregate statistics ===")
        aggregate_ids_to_mark = []
        for row in events:
            event_id, event_date, facility, event_type, count, description, article_id, is_agg = row
            # Aggregate if: no facility AND high count AND not already marked
            if facility is None and count is not None and count > 1 and not is_agg:
                aggregate_ids_to_mark.append(event_id)
                if len(aggregate_ids_to_mark) <= 10:
                    print(f"  Mark as aggregate: ID {event_id}, type={event_type}, count={count}")

        if len(aggregate_ids_to_mark) > 10:
            print(f"  ... and {len(aggregate_ids_to_mark) - 10} more")
        print(f"Total to mark as aggregate: {len(aggregate_ids_to_mark)}")
        results["aggregates_marked"] = len(aggregate_ids_to_mark)

        # Step 2: Identify duplicates (excluding aggregates)
        # Group by (date, normalized_facility, event_type)
        print("\n=== Step 2: Identifying duplicate events ===")
        groups: dict[tuple, list] = defaultdict(list)
        for row in events:
            event_id, event_date, facility, event_type, count, description, article_id, is_agg = row
            # Skip aggregates (already marked or will be marked)
            if is_agg or event_id in aggregate_ids_to_mark:
                continue
            if event_date is None:
                continue  # Skip events without date
            if facility is None:
                continue  # Skip events without facility (likely aggregates)

            normalized = normalize_facility_name(facility) or facility
            key = (event_date, normalized, event_type)
            groups[key].append(
                {
                    "id": event_id,
                    "facility": facility,
                    "count": count,
                    "description": description,
                    "article_id": article_id,
                }
            )

        duplicate_ids = []
        for key, event_list in groups.items():
            if len(event_list) > 1:
                # Keep the one with the longest description (most informative)
                sorted_events = sorted(
                    event_list,
                    key=lambda e: len(e["description"] or ""),
                    reverse=True,
                )
                keep = sorted_events[0]
                remove = sorted_events[1:]

                if len(duplicate_ids) < 30:  # Show first few
                    date, facility, etype = key
                    print(f"\n  {date} | {facility} | {etype}")
                    print(f"    KEEP: ID {keep['id']} (desc len: {len(keep['description'] or '')})")
                    for r in remove:
                        print(f"    REMOVE: ID {r['id']} (desc len: {len(r['description'] or '')})")

                duplicate_ids.extend(r["id"] for r in remove)

        print(f"\nTotal duplicates to remove: {len(duplicate_ids)}")
        results["duplicates_removed"] = len(duplicate_ids)

        # Step 3: Apply changes
        results["after_count"] = results["before_count"] - len(duplicate_ids)

        if not dry_run:
            print("\n=== Applying changes ===")

            # Mark aggregates
            if aggregate_ids_to_mark:
                session.execute(
                    text("UPDATE prison_events SET is_aggregate = TRUE WHERE id = ANY(:ids)"),
                    {"ids": aggregate_ids_to_mark},
                )
                print(f"Marked {len(aggregate_ids_to_mark)} records as aggregates")

            # Delete duplicates in batches
            if duplicate_ids:
                batch_size = 100
                for i in range(0, len(duplicate_ids), batch_size):
                    batch = duplicate_ids[i : i + batch_size]
                    session.execute(
                        text("DELETE FROM prison_events WHERE id = ANY(:ids)"),
                        {"ids": batch},
                    )
                print(f"Deleted {len(duplicate_ids)} duplicate records")

            session.commit()
        else:
            print(f"\n[DRY RUN] Would mark {len(aggregate_ids_to_mark)} as aggregates")
            print(f"[DRY RUN] Would delete {len(duplicate_ids)} duplicates")

        print(f"\n=== Summary ===")
        print(f"Before: {results['before_count']} events")
        print(f"After cleanup: {results['after_count']} events (duplicates removed)")
        print(f"Aggregates marked: {results['aggregates_marked']} (filtered in queries)")
        print(f"Duplicates removed: {results['duplicates_removed']}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Cleanup prison_events data quality issues")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without making changes",
    )
    args = parser.parse_args()

    cleanup_events(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
