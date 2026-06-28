# ABOUTME: Stats dashboard and API routes for prison event visualization.
# ABOUTME: Provides Chart.js dashboard and JSON endpoints for incidents and capacity data.

from datetime import date, timedelta

import structlog
from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from behind_bars_pulse.db.repository import FacilitySnapshotRepository, PrisonEventRepository
from behind_bars_pulse.db.session import get_session
from behind_bars_pulse.services.analytics_service import AnalyticsService

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


# --- Analytics & Advanced Statistics Models ---


class AnomalyItem(BaseModel):
    """Calculated anomaly statistic for a single facility."""

    facility: str
    region: str
    active_count: int
    active_monthly_rate: float
    baseline_monthly_rate: float
    z_score: float
    severity: str
    is_anomaly: bool


class AnomalyResponse(BaseModel):
    """Response containing list of anomalous facilities."""

    anomalies: list[AnomalyItem]


class CorrelationDataPoint(BaseModel):
    """Data point correlating occupancy and incidents for a facility."""

    facility: str
    region: str
    occupancy_rate: float
    incident_count: int


class CorrelationResponse(BaseModel):
    """Response containing correlation index, data points, and message."""

    correlation_coefficient: float
    data_points: list[CorrelationDataPoint]
    message: str


# --- Analytics & Advanced Statistics Endpoints ---


@router.get("/stats/api/anomalies", response_model=AnomalyResponse)
async def api_anomalies(
    lookback_days: int = Query(180, ge=60, le=365, description="Lookback days for baseline"),
    active_days: int = Query(30, ge=7, le=60, description="Active observation window"),
):
    """Calculate and return facilities showing anomalous spikes in incidents."""
    analytics_svc = AnalyticsService()
    async with get_session() as session:
        anomalies = await analytics_svc.calculate_facility_anomalies(
            session=session,
            lookback_days=lookback_days,
            active_days=active_days,
        )

    return AnomalyResponse(
        anomalies=[
            AnomalyItem(
                facility=a["facility"],
                region=a["region"],
                active_count=a["active_count"],
                active_monthly_rate=a["active_monthly_rate"],
                baseline_monthly_rate=a["baseline_monthly_rate"],
                z_score=a["z_score"],
                severity=a["severity"],
                is_anomaly=a["is_anomaly"],
            )
            for a in anomalies
        ]
    )


@router.get("/stats/api/correlation", response_model=CorrelationResponse)
async def api_correlation(
    lookback_days: int = Query(180, ge=60, le=365, description="Lookback days for correlation analysis"),
):
    """Calculate and return correlation metrics between occupancy rate and incident count."""
    analytics_svc = AnalyticsService()
    async with get_session() as session:
        correlation = await analytics_svc.calculate_occupancy_incident_correlation(
            session=session,
            lookback_days=lookback_days,
        )

    return CorrelationResponse(
        correlation_coefficient=correlation["correlation_coefficient"],
        message=correlation["message"],
        data_points=[
            CorrelationDataPoint(
                facility=dp["facility"],
                region=dp["region"],
                occupancy_rate=dp["occupancy_rate"],
                incident_count=dp["incident_count"],
            )
            for dp in correlation["data_points"]
        ],
    )


# --- Semantic Trends Models ---


class MonthlyTrendItem(BaseModel):
    """Semantic trend indicators for a single month."""

    month: str
    label: str
    article_count: int
    keywords: list[str]
    similarity: float
    drift: float


class SemanticDriftResponse(BaseModel):
    """Response containing chronological list of monthly semantic indicators."""

    trends: list[MonthlyTrendItem]


# --- Semantic Trends Endpoints ---


@router.get("/stats/api/semantic-drift", response_model=SemanticDriftResponse)
async def api_semantic_drift(
    refresh: bool = Query(False, description="Forza il ricalcolo e bypassa la cache"),
):
    """Get monthly semantic centroids drift (cosine distance) and keywords."""
    analytics_svc = AnalyticsService()
    async with get_session() as session:
        trends = await analytics_svc.calculate_semantic_trends(
            session=session,
            force_refresh=refresh,
        )

    return SemanticDriftResponse(
        trends=[
            MonthlyTrendItem(
                month=t["month"],
                label=t["label"],
                article_count=t["article_count"],
                keywords=t["keywords"],
                similarity=t["similarity"],
                drift=t["drift"],
            )
            for t in trends
        ]
    )
