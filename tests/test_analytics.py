# ABOUTME: Unit tests for the AnalyticsService and advanced stats endpoints.
# ABOUTME: Verifies Pearson correlation index and rolling Z-score anomaly calculations.

import math
from datetime import date, datetime, UTC, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from behind_bars_pulse.db.models import FacilitySnapshot, PrisonEvent
from behind_bars_pulse.services.analytics_service import AnalyticsService
from behind_bars_pulse.web.app import create_app
from behind_bars_pulse.web.dependencies import get_db_session


@pytest.fixture
def mock_db_session():
    """Create a mock AsyncSession."""
    return AsyncMock()


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


@pytest.mark.anyio
async def test_calculate_facility_anomalies_no_events(mock_db_session):
    """Test anomaly calculations when no events are returned."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db_session.execute.return_value = mock_result

    service = AnalyticsService()
    anomalies = await service.calculate_facility_anomalies(mock_db_session)
    assert anomalies == []


@pytest.mark.anyio
async def test_calculate_facility_anomalies_success(mock_db_session):
    """Test anomaly detection identifies a significant spike (high Z-score)."""
    today_date = date.today()
    
    # Create baseline events (1 event per week for 21 weeks)
    events = []
    for week in range(21):
        events.append(
            PrisonEvent(
                id=week,
                event_type="self_harm",
                event_date=today_date - timedelta(days=35 + week * 7),
                facility="San Vittore",
                region="Lombardia",
                count=1,
            )
        )
        
    # Create a severe active spike (12 events in the last 30 days)
    for i in range(12):
        events.append(
            PrisonEvent(
                id=100 + i,
                event_type="self_harm",
                event_date=today_date - timedelta(days=2 + i),
                facility="San Vittore",
                region="Lombardia",
                count=1,
            )
        )

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = events
    mock_db_session.execute.return_value = mock_result

    service = AnalyticsService()
    anomalies = await service.calculate_facility_anomalies(mock_db_session)
    
    assert len(anomalies) == 1
    anomaly = anomalies[0]
    assert anomaly["facility"] == "San Vittore"
    assert anomaly["active_count"] == 12
    assert anomaly["z_score"] > 2.0  # Spike is mathematically highly significant
    assert anomaly["severity"] in ["Alta", "Critica"]
    assert anomaly["is_anomaly"] is True


@pytest.mark.anyio
async def test_calculate_correlation_insufficient_data(mock_db_session):
    """Test correlation returns empty/fallback when database lacks data points."""
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_db_session.execute.return_value = mock_result

    service = AnalyticsService()
    correlation = await service.calculate_occupancy_incident_correlation(mock_db_session)
    assert correlation["correlation_coefficient"] == 0.0
    assert correlation["data_points"] == []
    assert "Nessun dato" in correlation["message"]


@pytest.mark.anyio
async def test_calculate_correlation_success(mock_db_session):
    """Test Pearson correlation calculation on standard sample facilities."""
    today_date = date.today()
    
    # 3 facilities:
    # F1: 180% occupancy, 10 incidents (high)
    # F2: 120% occupancy, 4 incidents (medium)
    # F3: 90% occupancy, 1 incident (low)
    
    snapshots = [
        FacilitySnapshot(facility="F1", region="Reg1", snapshot_date=today_date, occupancy_rate=180.0, source_url="u1"),
        FacilitySnapshot(facility="F2", region="Reg2", snapshot_date=today_date, occupancy_rate=120.0, source_url="u2"),
        FacilitySnapshot(facility="F3", region="Reg3", snapshot_date=today_date, occupancy_rate=90.0, source_url="u3"),
    ]
    
    events = []
    for i in range(10):
        events.append(PrisonEvent(facility="F1", region="Reg1", event_date=today_date - timedelta(days=i), event_type="suicide", description="d", source_url="u1"))
    for i in range(4):
        events.append(PrisonEvent(facility="F2", region="Reg2", event_date=today_date - timedelta(days=i), event_type="suicide", description="d", source_url="u2"))
    for i in range(1):
        events.append(PrisonEvent(facility="F3", region="Reg3", event_date=today_date - timedelta(days=i), event_type="suicide", description="d", source_url="u3"))

    # Mock DB executions
    # execute() is called twice inside calculate_occupancy_incident_correlation:
    # First call: select snapshots
    # Second call: select events
    mock_db_session.execute = AsyncMock()
    
    mock_res_snapshots = MagicMock()
    mock_res_snapshots.scalars.return_value.all.return_value = snapshots
    
    mock_res_events = MagicMock()
    mock_res_events.scalars.return_value.all.return_value = events
    
    mock_db_session.execute.side_effect = [mock_res_snapshots, mock_res_events]

    service = AnalyticsService()
    correlation = await service.calculate_occupancy_incident_correlation(mock_db_session)
    
    assert len(correlation["data_points"]) == 3
    # Pearson index should be positive and high (almost 1.0 because of perfectly linear sample)
    assert correlation["correlation_coefficient"] > 0.9
    assert "correlazione positiva" in correlation["message"]


def test_api_anomalies_endpoint(test_client, mock_db_session):
    """Test FastAPI endpoint /stats/api/anomalies responds with valid JSON schema."""
    # Mock data to be returned by AnalyticsService
    mock_anomalies = [
        {
            "facility": "Poggioreale",
            "region": "Campania",
            "active_count": 5,
            "active_monthly_rate": 5.0,
            "baseline_monthly_rate": 1.2,
            "z_score": 2.5,
            "severity": "Alta",
            "is_anomaly": True,
        }
    ]
    
    with patch.object(AnalyticsService, "calculate_facility_anomalies", AsyncMock(return_value=mock_anomalies)):
        response = test_client.get("/stats/api/anomalies")
        
        assert response.status_code == 200
        data = response.json()
        assert "anomalies" in data
        assert len(data["anomalies"]) == 1
        assert data["anomalies"][0]["facility"] == "Poggioreale"
        assert data["anomalies"][0]["severity"] == "Alta"
        assert data["anomalies"][0]["is_anomaly"] is True


def test_api_correlation_endpoint(test_client, mock_db_session):
    """Test FastAPI endpoint /stats/api/correlation responds with valid JSON schema."""
    # Mock data to be returned by AnalyticsService
    mock_correlation = {
        "correlation_coefficient": 0.85,
        "message": "Forte correlazione positiva rilevata.",
        "data_points": [
            {
                "facility": "Sollicciano",
                "region": "Toscana",
                "occupancy_rate": 142.0,
                "incident_count": 8,
            }
        ]
    }
    
    with patch.object(AnalyticsService, "calculate_occupancy_incident_correlation", AsyncMock(return_value=mock_correlation)):
        response = test_client.get("/stats/api/correlation")
        
        assert response.status_code == 200
        data = response.json()
        assert data["correlation_coefficient"] == 0.85
        assert "Forte correlazione" in data["message"]
        assert len(data["data_points"]) == 1
        assert data["data_points"][0]["facility"] == "Sollicciano"
        assert data["data_points"][0]["occupancy_rate"] == 142.0
