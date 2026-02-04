# ABOUTME: Stats dashboard and API routes for prison event visualization.
# ABOUTME: Provides Chart.js dashboard and JSON endpoints for incidents and capacity data.

from datetime import date, timedelta

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from behind_bars_pulse.db.repository import FacilitySnapshotRepository, PrisonEventRepository
from behind_bars_pulse.db.session import get_session

router = APIRouter(tags=["stats"])
log = structlog.get_logger()


class TimelineEvent(BaseModel):
    """Single event for timeline visualization."""

    date: str
    type: str
    count: int | None
    facility: str | None
    description: str


class TimelineResponse(BaseModel):
    """Timeline API response."""

    events: list[TimelineEvent]


class ByTypeResponse(BaseModel):
    """Count by event type response."""

    suicide: int
    self_harm: int
    assault: int
    protest: int
    natural_death: int


class RegionCount(BaseModel):
    """Region with event count."""

    region: str
    count: int


class ByRegionResponse(BaseModel):
    """Count by region response."""

    regions: list[RegionCount]


class FacilityCount(BaseModel):
    """Facility with event count."""

    facility: str
    count: int


class ByFacilityResponse(BaseModel):
    """Count by facility response."""

    facilities: list[FacilityCount]


class MonthlyCount(BaseModel):
    """Monthly count for charts."""

    month: str
    count: int


class MonthlyResponse(BaseModel):
    """Monthly counts response."""

    data: list[MonthlyCount]


@router.get("/stats", response_class=HTMLResponse)
async def stats_dashboard(request: Request):
    """Render the stats dashboard page with Chart.js visualizations."""
    templates = request.app.state.templates
    return templates.TemplateResponse(
        "stats.html",
        {"request": request},
    )


@router.get("/stats/api/timeline", response_model=TimelineResponse)
async def api_timeline(
    event_type: str | None = Query(None, description="Filter by event type"),
    days: int = Query(365, ge=7, le=730, description="Number of days to include"),
):
    """Get events for timeline visualization."""
    date_from = date.today() - timedelta(days=days)

    async with get_session() as session:
        repo = PrisonEventRepository(session)
        events = await repo.get_timeline(
            event_type=event_type,
            date_from=date_from,
            limit=200,
        )

    return TimelineResponse(
        events=[
            TimelineEvent(
                date=e.event_date.isoformat() if e.event_date else "",
                type=e.event_type,
                count=e.count,
                facility=e.facility,
                description=e.description[:200] if e.description else "",
            )
            for e in events
        ]
    )


@router.get("/stats/api/by-type", response_model=ByTypeResponse)
async def api_by_type(
    days: int = Query(365, ge=7, le=730, description="Number of days to include"),
):
    """Get event counts grouped by type."""
    date_from = date.today() - timedelta(days=days)

    async with get_session() as session:
        repo = PrisonEventRepository(session)
        counts = await repo.count_by_type(date_from=date_from)

    return ByTypeResponse(
        suicide=counts.get("suicide", 0),
        self_harm=counts.get("self_harm", 0),
        assault=counts.get("assault", 0),
        protest=counts.get("protest", 0),
        natural_death=counts.get("natural_death", 0),
    )


@router.get("/stats/api/by-region", response_model=ByRegionResponse)
async def api_by_region(
    event_type: str | None = Query(None, description="Filter by event type"),
    days: int = Query(365, ge=7, le=730, description="Number of days to include"),
):
    """Get event counts grouped by region."""
    date_from = date.today() - timedelta(days=days)

    async with get_session() as session:
        repo = PrisonEventRepository(session)
        counts = await repo.count_by_region(
            event_type=event_type,
            date_from=date_from,
        )

    # Sort by count descending
    sorted_regions = sorted(counts.items(), key=lambda x: x[1], reverse=True)

    return ByRegionResponse(regions=[RegionCount(region=r, count=c) for r, c in sorted_regions])


@router.get("/stats/api/by-facility", response_model=ByFacilityResponse)
async def api_by_facility(
    event_type: str | None = Query(None, description="Filter by event type"),
    limit: int = Query(15, ge=5, le=50, description="Number of facilities to return"),
):
    """Get event counts grouped by facility (top N)."""
    async with get_session() as session:
        repo = PrisonEventRepository(session)
        counts = await repo.count_by_facility(
            event_type=event_type,
            limit=limit,
        )

    return ByFacilityResponse(facilities=[FacilityCount(facility=f, count=c) for f, c in counts])


@router.get("/stats/api/by-month", response_model=MonthlyResponse)
async def api_by_month(
    event_type: str | None = Query(None, description="Filter by event type"),
    months: int = Query(12, ge=3, le=24, description="Number of months to include"),
):
    """Get event counts grouped by month."""
    date_from = date.today() - timedelta(days=months * 30)

    async with get_session() as session:
        repo = PrisonEventRepository(session)
        counts = await repo.count_by_month(
            event_type=event_type,
            date_from=date_from,
        )

    return MonthlyResponse(data=[MonthlyCount(month=m, count=c) for m, c in counts])


# --- Capacity API Models ---


class FacilityCapacity(BaseModel):
    """Capacity data for a single facility."""

    facility: str
    region: str | None
    inmates: int | None
    capacity: int | None
    occupancy_rate: float | None
    snapshot_date: str


class CapacityLatestResponse(BaseModel):
    """Latest capacity data for all facilities."""

    facilities: list[FacilityCapacity]


class CapacityTrendPoint(BaseModel):
    """Single point in capacity trend."""

    date: str
    total_inmates: int
    total_capacity: int
    avg_occupancy: float


class CapacityTrendResponse(BaseModel):
    """National capacity trend over time."""

    data: list[CapacityTrendPoint]


class RegionalCapacity(BaseModel):
    """Capacity summary for a region."""

    region: str
    total_inmates: int
    total_capacity: int
    avg_occupancy: float


class CapacityByRegionResponse(BaseModel):
    """Capacity summary by region."""

    regions: list[RegionalCapacity]


# --- Capacity API Endpoints ---


@router.get("/stats/api/capacity/latest", response_model=CapacityLatestResponse)
async def api_capacity_latest():
    """Get latest capacity snapshot for each facility (normalized)."""
    async with get_session() as session:
        repo = FacilitySnapshotRepository(session)
        snapshots = await repo.get_latest_by_facility()

    return CapacityLatestResponse(
        facilities=[
            FacilityCapacity(
                facility=s["facility"],
                region=s["region"],
                inmates=s["inmates"],
                capacity=s["capacity"],
                occupancy_rate=s["occupancy_rate"],
                snapshot_date=s["snapshot_date"].isoformat() if s["snapshot_date"] else "",
            )
            for s in snapshots
        ]
    )


@router.get("/stats/api/capacity/trend", response_model=CapacityTrendResponse)
async def api_capacity_trend(
    days: int = Query(365, ge=30, le=730, description="Number of days to include"),
):
    """Get national capacity trend over time."""
    date_from = date.today() - timedelta(days=days)

    async with get_session() as session:
        repo = FacilitySnapshotRepository(session)
        trend = await repo.get_national_trend(date_from=date_from)

    return CapacityTrendResponse(
        data=[
            CapacityTrendPoint(
                date=d.isoformat(),
                total_inmates=inmates,
                total_capacity=cap,
                avg_occupancy=round(occ, 1),
            )
            for d, inmates, cap, occ in trend
        ]
    )


@router.get("/stats/api/capacity/by-region", response_model=CapacityByRegionResponse)
async def api_capacity_by_region():
    """Get capacity summary by region (latest data)."""
    async with get_session() as session:
        repo = FacilitySnapshotRepository(session)
        summary = await repo.get_regional_summary()

    return CapacityByRegionResponse(
        regions=[
            RegionalCapacity(
                region=region,
                total_inmates=inmates,
                total_capacity=cap,
                avg_occupancy=round(occ, 1),
            )
            for region, inmates, cap, occ in summary
        ]
    )
