# ABOUTME: Unit tests for the FacilityDossierService and facilities routes.
# ABOUTME: Verifies AI dossier generation, local file caching, and views.

import json
import os
from datetime import date, datetime, UTC, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from behind_bars_pulse.db.models import FacilitySnapshot, PrisonEvent
from behind_bars_pulse.services.dossier_service import FacilityDossierService
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


def test_dossier_service_cache_mechanism(tmp_path):
    """Test get_cached_dossier and save cache in FacilityDossierService."""
    service = FacilityDossierService()
    # Override cache directory to use a temp path
    service.cache_dir = tmp_path
    
    facility = "Regina Coeli"
    content = "# Monografia Regina Coeli\n\nContenuto del dossier."
    
    # 1. Initially should be None
    assert service.get_cached_dossier(facility) is None
    
    # 2. Save to cache
    service._save_to_cache(facility, content)
    
    # 3. Load from cache (should match)
    cached = service.get_cached_dossier(facility)
    assert cached == content
    
    # 4. Expiry: modify the file to make it 10 days old
    cache_path = service._get_cache_path(facility)
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        
    old_time = datetime.now(UTC) - timedelta(days=10)
    data["generated_at"] = old_time.isoformat()
    
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(data, f)
        
    # Loaded dossier should now be expired (None)
    assert service.get_cached_dossier(facility) is None


@pytest.mark.anyio
async def test_get_or_generate_dossier_with_existing_cache(tmp_path, mock_db_session):
    """Test get_or_generate_dossier uses cache when available without querying AI."""
    service = FacilityDossierService()
    service.cache_dir = tmp_path
    
    facility = "San Vittore"
    content = "# Dossier San Vittore\n\nCached."
    service._save_to_cache(facility, content)
    
    # Run service
    dossier = await service.get_or_generate_dossier(
        session=mock_db_session,
        facility_name=facility,
        force_refresh=False,
    )
    
    assert dossier == content
    # Assert DB and AI were not queried
    assert mock_db_session.execute.call_count == 0


@pytest.mark.anyio
async def test_get_or_generate_dossier_queries_ai_on_cache_miss(tmp_path, mock_db_session):
    """Test get_or_generate_dossier queries DB/RAG/AI and saves on cache miss."""
    mock_ai = MagicMock()
    mock_ai.generate_facility_dossier.return_value = "# Generated Monograph"
    
    service = FacilityDossierService(ai_service=mock_ai)
    service.cache_dir = tmp_path
    
    # Mock database executes (snapshots and events)
    mock_db_session.execute = AsyncMock()
    mock_snapshots_res = MagicMock()
    mock_snapshots_res.scalars.return_value.all.return_value = [
        FacilitySnapshot(facility="Poggioreale", region="Campania", snapshot_date=date.today(), inmates=2000, capacity=1400)
    ]
    mock_events_res = MagicMock()
    mock_events_res.scalars.return_value.all.return_value = [
        PrisonEvent(facility="Poggioreale", region="Campania", event_date=date.today(), event_type="suicide")
    ]
    mock_db_session.execute.side_effect = [mock_snapshots_res, mock_events_res]
    
    # Mock RAG Service
    with patch.object(service.rag_service, "retrieve_historical_context", AsyncMock(return_value="RAG Comment")):
        dossier = await service.get_or_generate_dossier(
            session=mock_db_session,
            facility_name="Poggioreale",
            force_refresh=True,  # Force refresh to ignore cache
        )
        
        assert dossier == "# Generated Monograph"
        mock_ai.generate_facility_dossier.assert_called_once()
        
        # Verify it was saved to cache
        assert service.get_cached_dossier("Poggioreale") == "# Generated Monograph"


def test_list_facilities_route(test_client, mock_db_session):
    """Test /istituti router renders list successfully."""
    # Mock database results
    mock_snapshot = FacilitySnapshot(
        facility="Poggioreale",
        region="Campania",
        snapshot_date=date.today(),
        inmates=2000,
        capacity=1400,
        occupancy_rate=142.8,
    )
    
    mock_snapshots_res = MagicMock()
    mock_snapshots_res.scalars.return_value.all.return_value = [mock_snapshot]
    
    mock_regions_res = MagicMock()
    mock_regions_res.all.return_value = [("Campania",)]
    
    mock_events_res = MagicMock()
    mock_events_res.all.return_value = [("Poggioreale", 3)]
    
    mock_db_session.execute = AsyncMock()
    mock_db_session.execute.side_effect = [
        mock_snapshots_res,
        mock_regions_res,
        mock_events_res,
    ]

    response = test_client.get("/istituti")
    
    assert response.status_code == 200
    assert "Monografie degli Istituti" in response.text
    assert "Poggioreale" in response.text
    assert "Campania" in response.text


def test_view_facility_route(test_client, mock_db_session):
    """Test /istituto/{facility_name} router renders monograph successfully."""
    mock_snapshot = FacilitySnapshot(
        facility="Sollicciano",
        region="Toscana",
        snapshot_date=date.today(),
        inmates=800,
        capacity=500,
        occupancy_rate=160.0,
    )
    
    mock_db_session.execute = AsyncMock()
    mock_snapshot_res = MagicMock()
    mock_snapshot_res.scalar_one_or_none.return_value = mock_snapshot
    
    mock_count_res = MagicMock()
    mock_count_res.scalar.return_value = 12
    
    mock_db_session.execute.side_effect = [
        mock_snapshot_res,
        mock_count_res,
    ]
    
    with patch.object(FacilityDossierService, "get_or_generate_dossier", AsyncMock(return_value="# Dossier Sollicciano")):
        response = test_client.get("/istituto/Sollicciano")
        
        assert response.status_code == 200
        assert "Sollicciano" in response.text
        assert "Toscana" in response.text
        assert "Dossier Sollicciano" in response.text
