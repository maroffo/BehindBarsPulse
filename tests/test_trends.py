# ABOUTME: Unit tests for the semantic trend and embedding drift analysis.
# ABOUTME: Verifies monthly centroid calculations, cosine distance, and endpoints.

import json
import os
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from behind_bars_pulse.db.models import Article
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
async def test_calculate_semantic_trends_no_articles(mock_db_session):
    """Test semantic trend analysis when database has no embedded articles."""
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_db_session.execute.return_value = mock_result

    service = AnalyticsService()
    trends = await service.calculate_semantic_trends(mock_db_session, force_refresh=True)
    assert trends == []


@pytest.mark.anyio
async def test_calculate_semantic_trends_success(mock_db_session, tmp_path):
    """Test calculating semantic centroids, cosine similarity, and keyword extraction."""
    # Create articles with 768-dimensional mock embeddings
    # Month 1 (Jan 2026): all articles embedded close to [0.1, 0.1, ...]
    # Month 2 (Feb 2026): all articles embedded close to [0.15, 0.15, ...] (close, high similarity)
    emb_jan = [0.1] * 768
    emb_feb = [0.12] * 768  # Highly similar to Jan

    mock_row_jan = (date(2026, 1, 15), "Rivolta a San Vittore", emb_jan)
    mock_row_feb = (date(2026, 2, 10), "Suicidio a Regina Coeli", emb_feb)

    mock_result = MagicMock()
    mock_result.all.return_value = [mock_row_jan, mock_row_feb]
    mock_db_session.execute.return_value = mock_result

    # Mock AIService monthly keywords generator
    mock_ai_class = MagicMock()
    mock_ai = MagicMock()
    mock_ai.generate_monthly_themes.side_effect = [
        ["Rivolte", "San Vittore", "Disordini"],
        ["Suicidi", "Regina Coeli", "Emergenza"]
    ]
    
    with (
        patch("behind_bars_pulse.ai.service.AIService") as mock_ai_class,
        patch("behind_bars_pulse.config.get_settings") as mock_settings_fn,
    ):
        mock_ai_class.return_value = mock_ai
        
        # Override cache directory to temp path via settings
        mock_settings = MagicMock()
        mock_settings.templates_dir = tmp_path
        mock_settings_fn.return_value = mock_settings
        
        service = AnalyticsService()
        trends = await service.calculate_semantic_trends(mock_db_session, force_refresh=True)
        
        assert len(trends) == 2
        assert trends[0]["month"] == "2026-01"
        assert trends[0]["label"] == "Gennaio 2026"
        assert trends[0]["article_count"] == 1
        assert trends[0]["keywords"] == ["Rivolte", "San Vittore", "Disordini"]
        assert trends[0]["similarity"] == 1.0  # First month has self-similarity 1.0
        
        assert trends[1]["month"] == "2026-02"
        assert trends[1]["label"] == "Febbraio 2026"
        assert trends[1]["article_count"] == 1
        assert trends[1]["keywords"] == ["Suicidi", "Regina Coeli", "Emergenza"]
        # Cosine similarity of identical ratios should be exactly 1.0
        assert trends[1]["similarity"] == 1.0
        assert trends[1]["drift"] == 0.0


def test_api_semantic_drift_endpoint(test_client):
    """Test FastAPI endpoint /stats/api/semantic-drift responds with valid JSON schema."""
    mock_trends = [
        {
            "month": "2026-01",
            "label": "Gennaio 2026",
            "article_count": 12,
            "keywords": ["Tema1", "Tema2", "Tema3"],
            "similarity": 1.0,
            "drift": 0.0,
        }
    ]
    
    with patch.object(AnalyticsService, "calculate_semantic_trends", AsyncMock(return_value=mock_trends)):
        response = test_client.get("/stats/api/semantic-drift")
        
        assert response.status_code == 200
        data = response.json()
        assert "trends" in data
        assert len(data["trends"]) == 1
        assert data["trends"][0]["month"] == "2026-01"
        assert data["trends"][0]["keywords"] == ["Tema1", "Tema2", "Tema3"]
        assert data["trends"][0]["similarity"] == 1.0
