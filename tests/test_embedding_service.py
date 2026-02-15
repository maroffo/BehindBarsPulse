# ABOUTME: Tests for EmbeddingService extracted from NewsletterService.
# ABOUTME: Verifies embedding generation, client init, and delegation patterns.

from unittest.mock import MagicMock, patch

import pytest

from behind_bars_pulse.services.embedding_service import EMBEDDING_MODEL, EmbeddingService


class TestEmbeddingServiceInit:
    """Tests for EmbeddingService initialization."""

    def test_init_creates_instance(self) -> None:
        """EmbeddingService should initialize with no client."""
        svc = EmbeddingService()
        assert svc._genai_client is None

    @patch("behind_bars_pulse.services.embedding_service.get_settings")
    @patch("behind_bars_pulse.services.embedding_service.genai.Client")
    def test_genai_client_lazy_init(self, mock_client_cls, mock_settings) -> None:
        """genai_client property should lazy-init the client."""
        mock_key = MagicMock()
        mock_key.get_secret_value.return_value = "test-key"
        mock_settings.return_value.gemini_api_key = mock_key

        svc = EmbeddingService()
        client = svc.genai_client

        mock_client_cls.assert_called_once_with(api_key="test-key")
        assert client == mock_client_cls.return_value

    @patch("behind_bars_pulse.services.embedding_service.get_settings")
    def test_genai_client_raises_without_key(self, mock_settings) -> None:
        """genai_client should raise ValueError when no API key configured."""
        mock_settings.return_value.gemini_api_key = None

        svc = EmbeddingService()
        with pytest.raises(ValueError, match="GEMINI_API_KEY is required"):
            _ = svc.genai_client

    @patch("behind_bars_pulse.services.embedding_service.get_settings")
    @patch("behind_bars_pulse.services.embedding_service.genai.Client")
    def test_genai_client_cached(self, mock_client_cls, mock_settings) -> None:
        """genai_client should return cached client on subsequent calls."""
        mock_key = MagicMock()
        mock_key.get_secret_value.return_value = "test-key"
        mock_settings.return_value.gemini_api_key = mock_key

        svc = EmbeddingService()
        client1 = svc.genai_client
        client2 = svc.genai_client

        mock_client_cls.assert_called_once()
        assert client1 is client2


class TestEmbedText:
    """Tests for _embed_text method."""

    def test_embed_text_returns_floats(self) -> None:
        """_embed_text should return list of floats from API response."""
        svc = EmbeddingService()
        mock_embedding = MagicMock()
        mock_embedding.values = [0.1, 0.2, 0.3]
        mock_response = MagicMock()
        mock_response.embeddings = [mock_embedding]

        svc._genai_client = MagicMock()
        svc._genai_client.models.embed_content.return_value = mock_response

        result = svc._embed_text("test text")

        assert result == [0.1, 0.2, 0.3]
        svc._genai_client.models.embed_content.assert_called_once()

        # Verify RETRIEVAL_DOCUMENT task type
        call_kwargs = svc._genai_client.models.embed_content.call_args
        assert call_kwargs.kwargs["model"] == EMBEDDING_MODEL
        assert call_kwargs.kwargs["contents"] == "test text"

    def test_embed_text_raises_on_empty_response(self) -> None:
        """_embed_text should raise ValueError when API returns no embeddings."""
        svc = EmbeddingService()
        mock_response = MagicMock()
        mock_response.embeddings = []

        svc._genai_client = MagicMock()
        svc._genai_client.models.embed_content.return_value = mock_response

        with pytest.raises(ValueError, match="No embeddings returned"):
            svc._embed_text("test text")


class TestEmbedQuery:
    """Tests for _embed_query method."""

    def test_embed_query_uses_retrieval_query_task(self) -> None:
        """_embed_query should use RETRIEVAL_QUERY task type."""
        svc = EmbeddingService()
        mock_embedding = MagicMock()
        mock_embedding.values = [0.4, 0.5, 0.6]
        mock_response = MagicMock()
        mock_response.embeddings = [mock_embedding]

        svc._genai_client = MagicMock()
        svc._genai_client.models.embed_content.return_value = mock_response

        result = svc._embed_query("search query")

        assert result == [0.4, 0.5, 0.6]

    def test_embed_query_raises_on_empty_response(self) -> None:
        """_embed_query should raise ValueError when API returns no embeddings."""
        svc = EmbeddingService()
        mock_response = MagicMock()
        mock_response.embeddings = None

        svc._genai_client = MagicMock()
        svc._genai_client.models.embed_content.return_value = mock_response

        with pytest.raises(ValueError, match="No embeddings returned"):
            svc._embed_query("test query")


class TestGenerateEmbedding:
    """Tests for the async generate_embedding method."""

    @pytest.mark.asyncio
    async def test_generate_embedding_delegates_to_embed_query(self) -> None:
        """generate_embedding should delegate to _embed_query in executor."""
        svc = EmbeddingService()
        mock_embedding = MagicMock()
        mock_embedding.values = [0.7, 0.8, 0.9]
        mock_response = MagicMock()
        mock_response.embeddings = [mock_embedding]

        svc._genai_client = MagicMock()
        svc._genai_client.models.embed_content.return_value = mock_response

        result = await svc.generate_embedding("async query")

        assert result == [0.7, 0.8, 0.9]


class TestEmbeddingModelConstant:
    """Tests for the EMBEDDING_MODEL constant."""

    def test_embedding_model_value(self) -> None:
        """EMBEDDING_MODEL should be the expected model name."""
        assert EMBEDDING_MODEL == "models/gemini-embedding-001"


class TestImportPaths:
    """Tests verifying that the new import paths work correctly."""

    def test_import_from_services_init(self) -> None:
        """EmbeddingService should be importable from services package."""
        from behind_bars_pulse.services import EmbeddingService as SvcFromInit

        assert SvcFromInit is EmbeddingService

    def test_import_embedding_model_from_service(self) -> None:
        """EMBEDDING_MODEL should be importable from embedding_service module."""
        from behind_bars_pulse.services.embedding_service import (
            EMBEDDING_MODEL as model,
        )

        assert model == "models/gemini-embedding-001"
