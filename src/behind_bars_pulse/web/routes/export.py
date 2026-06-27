# ABOUTME: Data export endpoints for journalist download (CSV/JSON).
# ABOUTME: Exports prison events and capacity snapshots.

import csv
import json
from io import StringIO
from typing import Literal

import structlog
from fastapi import APIRouter, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from behind_bars_pulse.db.models import FacilitySnapshot, PrisonEvent
from behind_bars_pulse.web.dependencies import DbSession

router = APIRouter(prefix="/export", tags=["export"])
log = structlog.get_logger()


@router.get("/events")
async def export_events(
    session: DbSession,
    format: Literal["csv", "json"] = Query("csv", description="Export format (csv or json)"),
):
    """Export all prison events in CSV or JSON format."""
    log.info("exporting_prison_events", format=format)
    
    # Query all events, ordered by date descending
    result = await session.execute(
        select(PrisonEvent).order_by(PrisonEvent.event_date.desc().nulls_last())
    )
    events = result.scalars().all()

    if format == "json":
        data = [
            {
                "id": e.id,
                "event_type": e.event_type,
                "event_date": e.event_date.isoformat() if e.event_date else None,
                "facility": e.facility,
                "region": e.region,
                "count": e.count,
                "confidence": e.confidence,
                "is_aggregate": e.is_aggregate,
                "description": e.description,
                "source_url": e.source_url,
                "extracted_at": e.extracted_at.isoformat() if e.extracted_at else None,
            }
            for e in events
        ]
        return Response(
            content=json.dumps(data, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=prison_events.json"},
        )

    # Otherwise CSV format
    stream = StringIO()
    writer = csv.writer(stream, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
    
    # Write header
    writer.writerow([
        "id", "event_type", "event_date", "facility", "region", "count", 
        "confidence", "is_aggregate", "description", "source_url", "extracted_at"
    ])
    
    # Write data rows
    for e in events:
        writer.writerow([
            e.id,
            e.event_type,
            e.event_date.isoformat() if e.event_date else "",
            e.facility or "",
            e.region or "",
            e.count if e.count is not None else 1,
            e.confidence,
            1 if e.is_aggregate else 0,
            e.description or "",
            e.source_url or "",
            e.extracted_at.isoformat() if e.extracted_at else "",
        ])
        
    stream.seek(0)
    return StreamingResponse(
        stream,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=prison_events.csv"},
    )


@router.get("/capacity")
async def export_capacity(
    session: DbSession,
    format: Literal["csv", "json"] = Query("csv", description="Export format (csv or json)"),
):
    """Export all facility capacity snapshots in CSV or JSON format."""
    log.info("exporting_capacity_snapshots", format=format)
    
    # Query all snapshots, ordered by date descending
    result = await session.execute(
        select(FacilitySnapshot).order_by(FacilitySnapshot.snapshot_date.desc())
    )
    snapshots = result.scalars().all()

    if format == "json":
        data = [
            {
                "id": s.id,
                "facility": s.facility,
                "region": s.region,
                "snapshot_date": s.snapshot_date.isoformat() if s.snapshot_date else None,
                "inmates": s.inmates,
                "capacity": s.capacity,
                "occupancy_rate": s.occupancy_rate,
                "source_url": s.source_url,
                "extracted_at": s.extracted_at.isoformat() if s.extracted_at else None,
            }
            for s in snapshots
        ]
        return Response(
            content=json.dumps(data, indent=2, ensure_ascii=False),
            media_type="application/json",
            headers={"Content-Disposition": "attachment; filename=facility_capacity.json"},
        )

    # Otherwise CSV format
    stream = StringIO()
    writer = csv.writer(stream, delimiter=",", quotechar='"', quoting=csv.QUOTE_MINIMAL)
    
    # Write header
    writer.writerow([
        "id", "facility", "region", "snapshot_date", "inmates", "capacity", 
        "occupancy_rate", "source_url", "extracted_at"
    ])
    
    # Write data rows
    for s in snapshots:
        writer.writerow([
            s.id,
            s.facility or "",
            s.region or "",
            s.snapshot_date.isoformat() if s.snapshot_date else "",
            s.inmates if s.inmates is not None else "",
            s.capacity if s.capacity is not None else "",
            s.occupancy_rate if s.occupancy_rate is not None else "",
            s.source_url or "",
            s.extracted_at.isoformat() if s.extracted_at else "",
        ])
        
    stream.seek(0)
    return StreamingResponse(
        stream,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=facility_capacity.csv"},
    )
