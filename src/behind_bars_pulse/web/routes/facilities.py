# ABOUTME: Routes for prison facility listings and AI-generated dossiers.
# ABOUTME: Provides facility index page and individual prison monograph pages.

import structlog
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select, func

from behind_bars_pulse.db.models import FacilitySnapshot, PrisonEvent
from behind_bars_pulse.services.dossier_service import FacilityDossierService
from behind_bars_pulse.web.dependencies import DbSession, Templates

router = APIRouter(tags=["facilities"])
log = structlog.get_logger()


@router.get("/istituti", response_class=HTMLResponse)
async def list_facilities(
    request: Request,
    session: DbSession,
    templates: Templates,
    region: str | None = Query(None, description="Filtra per regione"),
):
    """Render the list of all prison facilities with key metrics."""
    log.info("rendering_facilities_list", region=region)

    # 1. Fetch latest capacity snapshots per facility
    # Subquery to find the latest date per facility
    subquery = (
        select(
            FacilitySnapshot.facility,
            func.max(FacilitySnapshot.snapshot_date).label("latest_date"),
        )
        .group_by(FacilitySnapshot.facility)
        .subquery()
    )

    query = (
        select(FacilitySnapshot)
        .join(
            subquery,
            (FacilitySnapshot.facility == subquery.c.facility)
            & (FacilitySnapshot.snapshot_date == subquery.c.latest_date),
        )
        .order_by(FacilitySnapshot.facility)
    )

    if region:
        query = query.where(FacilitySnapshot.region == region)

    snapshots_result = await session.execute(query)
    snapshots = snapshots_result.scalars().all()

    # 2. Fetch distinct regions for the filter dropdown
    regions_res = await session.execute(
        select(FacilitySnapshot.region)
        .where(FacilitySnapshot.region.isnot(None))
        .distinct()
        .order_by(FacilitySnapshot.region)
    )
    regions = [r[0] for r in regions_res.all()]

    # 3. Fetch total incident counts per facility to display in index
    events_res = await session.execute(
        select(PrisonEvent.facility, func.sum(PrisonEvent.count))
        .where(PrisonEvent.facility.isnot(None))
        .group_by(PrisonEvent.facility)
    )
    
    from collections import defaultdict
    from behind_bars_pulse.utils.facilities import normalize_facility_name

    # Map normalized names to sum of incidents
    normalized_incident_counts = defaultdict(int)
    for row in events_res.all():
        raw_facility = row[0]
        if raw_facility is not None:
            canonical = normalize_facility_name(raw_facility) or raw_facility
            count = int(row[1]) if row[1] is not None else 0
            normalized_incident_counts[canonical] += count

    # Map snapshots to dictionary and deduplicate by canonical name
    # We keep the one with the latest snapshot_date for each canonical name
    deduplicated = {}
    for s in snapshots:
        if not s.facility:
            continue
        canonical = normalize_facility_name(s.facility) or s.facility
        
        existing = deduplicated.get(canonical)
        # If no existing, or this snapshot is newer
        if not existing or (s.snapshot_date and (not existing["snapshot_date"] or s.snapshot_date > existing["snapshot_date"])):
            deduplicated[canonical] = {
                "facility": canonical,
                "region": s.region or "Sconosciuta",
                "inmates": s.inmates,
                "capacity": s.capacity,
                "occupancy_rate": s.occupancy_rate,
                "incident_count": 0,  # populated next
                "snapshot_date": s.snapshot_date,
            }

    # Assign combined incident counts
    facility_list = list(deduplicated.values())
    for f in facility_list:
        f["incident_count"] = normalized_incident_counts.get(f["facility"], 0)

    # Sort primarily by incident count or name
    facility_list.sort(key=lambda x: x["incident_count"], reverse=True)

    return templates.TemplateResponse(
        "facilities.html",
        {
            "request": request,
            "facilities": facility_list,
            "regions": regions,
            "selected_region": region,
        },
    )


@router.get("/istituto/{facility_name}", response_class=HTMLResponse)
async def view_facility(
    request: Request,
    facility_name: str,
    session: DbSession,
    templates: Templates,
    refresh: bool = Query(False, description="Forza rigenerazione dossier via AI"),
):
    """Render details and AI monograph dossier for a specific facility."""
    log.info("rendering_facility_monograph", facility=facility_name, force_refresh=refresh)

    # 1. Fetch latest statistics for the facility
    snapshots_res = await session.execute(
        select(FacilitySnapshot)
        .where(FacilitySnapshot.facility == facility_name)
        .order_by(FacilitySnapshot.snapshot_date.desc())
        .limit(1)
    )
    latest_snapshot = snapshots_res.scalar_one_or_none()

    # 2. Get total incidents in DB
    events_count_res = await session.execute(
        select(func.sum(PrisonEvent.count))
        .where(PrisonEvent.facility == facility_name)
    )
    total_incidents = events_count_res.scalar() or 0

    # 3. Load or generate the AI dossier
    dossier_svc = FacilityDossierService()
    dossier_md = await dossier_svc.get_or_generate_dossier(
        session=session,
        facility_name=facility_name,
        force_refresh=refresh,
    )

    # 4. Fetch all articles mentioning this facility name (case-insensitive)
    from behind_bars_pulse.db.models import Article
    articles_res = await session.execute(
        select(Article)
        .where(
            Article.title.ilike(f"%{facility_name}%") | 
            Article.content.ilike(f"%{facility_name}%")
        )
        .order_by(Article.published_date.desc().nulls_last())
        .limit(20)  # Limit to top 20 recent articles to keep page lightweight
    )
    mentioned_articles = articles_res.scalars().all()

    return templates.TemplateResponse(
        "facility.html",
        {
            "request": request,
            "facility_name": facility_name,
            "latest_snapshot": latest_snapshot,
            "total_incidents": total_incidents,
            "dossier": dossier_md,
            "refreshed": refresh,
            "articles": mentioned_articles,
        },
    )
