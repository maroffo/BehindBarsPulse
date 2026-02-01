# ABOUTME: Stats dashboard and API routes for prison event visualization.
# ABOUTME: Provides Chart.js dashboard and JSON endpoints for timeline, by-type, by-region data.

from datetime import date, timedelta

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from behind_bars_pulse.db.repository import PrisonEventRepository
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
    protest: int
    overcrowding: int


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
        protest=counts.get("protest", 0),
        overcrowding=counts.get("overcrowding", 0),
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
