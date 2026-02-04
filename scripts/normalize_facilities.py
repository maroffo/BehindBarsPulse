# ABOUTME: Script to normalize facility names in existing database records.
# ABOUTME: Merges duplicate facilities and recalculates statistics.

"""
Normalize Facility Names in Database

This script normalizes facility names in the prison_events and facility_snapshots
tables to consolidate duplicates (e.g., "Brescia Canton Mombello" and "Canton Mombello"
both become "Canton Mombello (Brescia)").

Usage:
    # Dry run - show what would change
    uv run python scripts/normalize_facilities.py --dry-run

    # Apply changes (via API endpoint in production)
    curl -X POST "https://behindbars.news/api/normalize-facilities?admin_token=YOUR_TOKEN"

The normalization mapping is in src/behind_bars_pulse/utils/facilities.py
"""

import argparse
import sys
from collections import Counter
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from behind_bars_pulse.config import get_settings
from behind_bars_pulse.utils.facilities import normalize_facility_name


def analyze_facilities(dry_run: bool = True) -> dict:
    """Analyze and optionally normalize facility names in database.

    Args:
        dry_run: If True, only analyze without making changes.

    Returns:
        Dictionary with analysis results.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    settings = get_settings()
    if not settings.database_url:
        print("ERROR: No database URL configured")
        return {"error": "No database URL"}

    # Use sync connection
    sync_url = settings.database_url_sync
    engine = create_engine(sync_url)

    results = {
        "prison_events": {"before": {}, "after": {}, "changes": []},
        "facility_snapshots": {"before": {}, "after": {}, "changes": []},
    }

    with Session(engine) as session:
        # Analyze prison_events
        print("\n=== Prison Events ===")
        events = session.execute(
            text("SELECT id, facility FROM prison_events WHERE facility IS NOT NULL")
        ).fetchall()

        before_counts = Counter()
        after_counts = Counter()
        changes = []

        for event_id, facility in events:
            before_counts[facility] += 1
            normalized = normalize_facility_name(facility)
            after_counts[normalized] += 1
            if facility != normalized:
                changes.append((event_id, facility, normalized))

        results["prison_events"]["before"] = dict(before_counts.most_common())
        results["prison_events"]["after"] = dict(after_counts.most_common())
        results["prison_events"]["changes"] = changes

        print(f"Total events with facility: {len(events)}")
        print(f"Unique facilities before: {len(before_counts)}")
        print(f"Unique facilities after: {len(after_counts)}")
        print(f"Records to update: {len(changes)}")

        if changes:
            print("\nSample changes:")
            for event_id, old, new in changes[:10]:
                print(f"  [{event_id}] '{old}' -> '{new}'")
            if len(changes) > 10:
                print(f"  ... and {len(changes) - 10} more")

        # Analyze facility_snapshots
        print("\n=== Facility Snapshots ===")
        snapshots = session.execute(
            text("SELECT id, facility FROM facility_snapshots WHERE facility IS NOT NULL")
        ).fetchall()

        before_counts = Counter()
        after_counts = Counter()
        changes = []

        for snap_id, facility in snapshots:
            before_counts[facility] += 1
            normalized = normalize_facility_name(facility)
            after_counts[normalized] += 1
            if facility != normalized:
                changes.append((snap_id, facility, normalized))

        results["facility_snapshots"]["before"] = dict(before_counts.most_common())
        results["facility_snapshots"]["after"] = dict(after_counts.most_common())
        results["facility_snapshots"]["changes"] = changes

        print(f"Total snapshots with facility: {len(snapshots)}")
        print(f"Unique facilities before: {len(before_counts)}")
        print(f"Unique facilities after: {len(after_counts)}")
        print(f"Records to update: {len(changes)}")

        if changes:
            print("\nSample changes:")
            for snap_id, old, new in changes[:10]:
                print(f"  [{snap_id}] '{old}' -> '{new}'")
            if len(changes) > 10:
                print(f"  ... and {len(changes) - 10} more")

        # Apply changes if not dry run
        if not dry_run:
            print("\n=== Applying Changes ===")

            # Update prison_events
            event_changes = results["prison_events"]["changes"]
            if event_changes:
                for event_id, _, normalized in event_changes:
                    session.execute(
                        text("UPDATE prison_events SET facility = :facility WHERE id = :id"),
                        {"facility": normalized, "id": event_id},
                    )
                print(f"Updated {len(event_changes)} prison_events records")

            # Update facility_snapshots
            snap_changes = results["facility_snapshots"]["changes"]
            if snap_changes:
                for snap_id, _, normalized in snap_changes:
                    session.execute(
                        text("UPDATE facility_snapshots SET facility = :facility WHERE id = :id"),
                        {"facility": normalized, "id": snap_id},
                    )
                print(f"Updated {len(snap_changes)} facility_snapshots records")

            session.commit()
            print("\nChanges committed successfully!")
        else:
            print("\n[DRY RUN] No changes made. Run without --dry-run to apply.")

    return results


def show_missing_aliases() -> None:
    """Show facilities that don't have normalization aliases."""
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session

    settings = get_settings()
    if not settings.database_url:
        print("ERROR: No database URL configured")
        return

    sync_url = settings.database_url_sync
    engine = create_engine(sync_url)

    with Session(engine) as session:
        # Get all unique facilities
        events = session.execute(
            text("SELECT DISTINCT facility FROM prison_events WHERE facility IS NOT NULL")
        ).fetchall()
        snapshots = session.execute(
            text("SELECT DISTINCT facility FROM facility_snapshots WHERE facility IS NOT NULL")
        ).fetchall()

        all_facilities = set(f[0] for f in events) | set(f[0] for f in snapshots)

        # Find facilities that normalize to themselves (no alias found)
        missing = []
        for facility in sorted(all_facilities):
            normalized = normalize_facility_name(facility)
            if normalized == facility or (normalized and normalized.lower() == facility.lower()):
                # Might be missing an alias
                missing.append(facility)

        print("\n=== Facilities Without Aliases ===")
        print("These facilities normalize to themselves (might need aliases):\n")
        for f in sorted(missing):
            print(f"  - {f}")
        print(f"\nTotal: {len(missing)} facilities")


def main():
    parser = argparse.ArgumentParser(description="Normalize facility names in database")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without making changes",
    )
    parser.add_argument(
        "--show-missing",
        action="store_true",
        help="Show facilities that might need new aliases",
    )
    args = parser.parse_args()

    if args.show_missing:
        show_missing_aliases()
    else:
        analyze_facilities(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
