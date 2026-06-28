# ABOUTME: Administrative script to trigger production database cleanup APIs.
# ABOUTME: Normalizes facility names and removes duplicate prison events.

"""
Production Database Cleanup Tool

This script connects to the production BehindBarsPulse API, authenticates using
the GEMINI_API_KEY from your local .env file, and triggers:
1. /api/normalize-facilities (to merge different spelling variations of prisons)
2. /api/cleanup-events (to deduplicate event records and mark aggregates)

Usage:
    # Run in dry-run mode (does not modify database)
    uv run python scripts/cleanup_production_data.py --dry-run

    # Run in apply mode (MODIFIES production database!)
    uv run python scripts/cleanup_production_data.py --apply
"""

import argparse
import json
import urllib.parse
import urllib.request
import sys
from pathlib import Path

# Add src folder to python path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from behind_bars_pulse.config import get_settings


def trigger_cleanup(dry_run: bool = True) -> bool:
    """Trigger the production cleanup APIs using the local .env credentials."""
    print("=== PRODUCTION DATABASE CLEANUP & DEDUPLICATION ===")
    print(f"Mode: {'[DRY-RUN] Preview only' if dry_run else '[APPLY] MODIFYING PRODUCTION DATABASE!'}")

    # 1. Load settings and API key
    try:
        settings = get_settings()
        if not settings.gemini_api_key:
            print("\n❌ ERROR: gemini_api_key is not configured in your .env file.")
            return False
            
        token = settings.gemini_api_key.get_secret_value()
    except Exception as e:
        print(f"\n❌ ERROR: Failed to load local .env settings: {e}")
        return False

    base_url = "https://behindbars-prod-208669631335.europe-west1.run.app"
    
    # 2. Trigger /api/normalize-facilities
    print("\n[1/2] Triggering facility normalization...")
    norm_params = urllib.parse.urlencode({
        "admin_token": token,
        "dry_run": "true" if dry_run else "false"
    })
    norm_url = f"{base_url}/api/normalize-facilities?{norm_params}"
    
    try:
        req = urllib.request.Request(norm_url, method="POST")
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            
        print("  ✅ SUCCESS: Normalization run completed!")
        print(f"  - Prison Events: {res_data.get('prison_events', {}).get('changes', 0)} changes proposed/made.")
        print(f"  - Facility Snapshots: {res_data.get('facility_snapshots', {}).get('changes', 0)} changes proposed/made.")
        
        samples = res_data.get("sample_changes", [])
        if samples:
            print("  - Sample variations unifications:")
            for s in samples[:5]:
                print(f"    * '{s.get('old')}' ➔ '{s.get('new')}'")
                
    except urllib.error.HTTPError as e:
        print(f"\n❌ ERROR: Normalization API call failed (HTTP {e.code}): {e.read().decode('utf-8')}")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: Normalization call failed: {e}")
        return False

    # 3. Trigger /api/cleanup-events
    print("\n[2/2] Triggering prison events cleanup and deduplication...")
    cleanup_params = urllib.parse.urlencode({
        "admin_token": token,
        "dry_run": "true" if dry_run else "false"
    })
    cleanup_url = f"{base_url := 'https://behindbars-prod-208669631335.europe-west1.run.app'}/api/stats/api/cleanup-prison-events?admin_token={urllib.parse.quote(token)}"
    
    # Wait, let's verify if the route is /api/stats/cleanup or /stats/api/cleanup or if there's a specific route.
    # Ah! In the standard router, it is `/stats/api/anomalies`, but let's check what the cleanup route in api.py is!
    # Let's verify what path is defined for cleanup_events in api.py!
    # In api.py, it was:
    # `@router.post("/cleanup-events")`
    # Let's verify if the endpoint in api.py is under /api/cleanup-events.
    # Since the prefix of router is `/api`, yes, it is `/api/cleanup-events`!
    # Let's use the correct URL: f"{base_url}/api/cleanup-events?{cleanup_params}"
    
    cleanup_url = f"{base_url}/api/cleanup-events?{cleanup_params}"
    
    try:
        req = urllib.request.Request(cleanup_url, method="POST")
        with urllib.request.urlopen(req) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            
        print("  ✅ SUCCESS: Events cleanup and deduplication completed!")
        print(f"  - Aggregate markers applied: {res_data.get('aggregates_marked', 0)}")
        print(f"  - Duplicate event rows removed: {res_data.get('duplicates_removed', 0)}")
        print(f"  - Events count: {res_data.get('before_count', 0)} ➔ {res_data.get('after_count', 0)}")
        
        duplicates = res_data.get("sample_duplicates", [])
        if duplicates:
            print("  - Sample duplicates merged:")
            for d in duplicates[:5]:
                print(f"    * Merged duplicate row IDs {d.get('remove_ids')} into main row ID {d.get('keep_id')} (Key: {d.get('key')})")
                
    except urllib.error.HTTPError as e:
        print(f"\n❌ ERROR: Cleanup API call failed (HTTP {e.code}): {e.read().decode('utf-8')}")
        return False
    except Exception as e:
        print(f"\n❌ ERROR: Cleanup call failed: {e}")
        return False

    print("\n🎉 PRODUCTION DATABASE CLEANUP COMPLETE!")
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trigger production DB cleanup and normalization")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply changes to the production database (omitting triggers a dry-run)",
    )
    
    args = parser.parse_args()
    
    success = trigger_cleanup(dry_run=not args.apply)
    sys.exit(0 if success else 1)
