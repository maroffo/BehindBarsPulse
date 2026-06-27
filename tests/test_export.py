# ABOUTME: Unit tests for the data export endpoints (CSV/JSON).
# ABOUTME: Verifies HTTP responses, headers, and format conversions.

import csv
import json
from datetime import date, datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from behind_bars_pulse.db.models import FacilitySnapshot, PrisonEvent
from behind_bars_pulse.web.app import create_app
from behind_bars_pulse.web.dependencies import get_db_session


@pytest.fixture
def mock_db_session():
    """Create a mock AsyncSession."""
    session = AsyncMock()
    return session


@pytest.fixture
def test_client(mock_db_session):
    """Create a test client with mocked database session."""
    with (
        patch("behind_bars_pulse.web.app.init_db", new_callable=AsyncMock),
        patch("behind_bars_pulse.web.app.close_db", new_callable=AsyncMock),
    ):
        app = create_app()

    app.dependency_overrides[get_db_session] = lambda: mock_db_session
    return TestClient(app)


def test_export_events_csv(test_client, mock_db_session):
    """Test exporting events as CSV."""
    # Create mock database events
    mock_event = PrisonEvent(
        id=1,
        event_type="suicide",
        event_date=date(2026, 2, 5),
        facility="Canton Mombello",
        region="Lombardia",
        count=1,
        confidence=1.0,
        is_aggregate=False,
        description="A tragic suicide event.",
        source_url="https://example.com/source",
        extracted_at=datetime(2026, 2, 5, 12, 0, 0, tzinfo=UTC),
    )
    
    # Mock database session execution
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_event]
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    response = test_client.get("/export/events?format=csv")
    
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert "attachment; filename=prison_events.csv" in response.headers["Content-Disposition"]
    
    # Parse CSV output
    csv_content = response.text
    reader = csv.reader(csv_content.splitlines())
    rows = list(reader)
    
    assert len(rows) == 2  # Header + 1 row
    assert rows[0][0] == "id"
    assert rows[0][1] == "event_type"
    assert rows[1][0] == "1"
    assert rows[1][1] == "suicide"
    assert rows[1][3] == "Canton Mombello"


def test_export_events_json(test_client, mock_db_session):
    """Test exporting events as JSON."""
    # Create mock database events
    mock_event = PrisonEvent(
        id=42,
        event_type="protest",
        event_date=date(2026, 1, 30),
        facility="San Vittore",
        region="Lombardia",
        count=10,
        confidence=0.9,
        is_aggregate=True,
        description="A peaceful protest.",
        source_url="https://example.com/source-protest",
        extracted_at=datetime(2026, 1, 30, 10, 0, 0, tzinfo=UTC),
    )
    
    # Mock database session execution
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_event]
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    response = test_client.get("/export/events?format=json")
    
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert "attachment; filename=prison_events.json" in response.headers["Content-Disposition"]
    
    # Parse JSON output
    data = json.loads(response.text)
    assert len(data) == 1
    assert data[0]["id"] == 42
    assert data[0]["event_type"] == "protest"
    assert data[0]["facility"] == "San Vittore"
    assert data[0]["is_aggregate"] is True


def test_export_capacity_csv(test_client, mock_db_session):
    """Test exporting capacity snapshots as CSV."""
    mock_snapshot = FacilitySnapshot(
        id=10,
        facility="Regina Coeli",
        region="Lazio",
        snapshot_date=date(2026, 2, 1),
        inmates=1100,
        capacity=600,
        occupancy_rate=183.3,
        source_url="https://example.com/capacity",
        extracted_at=datetime(2026, 2, 1, 15, 0, 0, tzinfo=UTC),
    )
    
    # Mock database session execution
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_snapshot]
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    response = test_client.get("/export/capacity?format=csv")
    
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "text/csv; charset=utf-8"
    assert "attachment; filename=facility_capacity.csv" in response.headers["Content-Disposition"]
    
    # Parse CSV output
    csv_content = response.text
    reader = csv.reader(csv_content.splitlines())
    rows = list(reader)
    
    assert len(rows) == 2  # Header + 1 row
    assert rows[0][0] == "id"
    assert rows[0][1] == "facility"
    assert rows[1][0] == "10"
    assert rows[1][1] == "Regina Coeli"
    assert rows[1][6] == "183.3"


def test_export_capacity_json(test_client, mock_db_session):
    """Test exporting capacity snapshots as JSON."""
    mock_snapshot = FacilitySnapshot(
        id=20,
        facility="Poggioreale",
        region="Campania",
        snapshot_date=date(2026, 2, 10),
        inmates=2000,
        capacity=1400,
        occupancy_rate=142.8,
        source_url="https://example.com/poggi",
        extracted_at=datetime(2026, 2, 10, 8, 0, 0, tzinfo=UTC),
    )
    
    # Mock database session execution
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [mock_snapshot]
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    response = test_client.get("/export/capacity?format=json")
    
    assert response.status_code == 200
    assert response.headers["Content-Type"] == "application/json"
    assert "attachment; filename=facility_capacity.json" in response.headers["Content-Disposition"]
    
    # Parse JSON output
    data = json.loads(response.text)
    assert len(data) == 1
    assert data[0]["id"] == 20
    assert data[0]["facility"] == "Poggioreale"
    assert data[0]["occupancy_rate"] == 142.8
