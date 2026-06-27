# ABOUTME: Unit tests for the RAGService (Retrieval-Augmented Generation).
# ABOUTME: Verifies both async and sync pgvector semantic search over editorial comments.

from datetime import date, datetime, UTC
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from behind_bars_pulse.db.models import EditorialComment
from behind_bars_pulse.services.rag_service import RAGService


@pytest.fixture
def sample_editorial_comments():
    """Create a list of mock EditorialComment models with mock similarity scores."""
    comment1 = EditorialComment(
        id=1,
        source_type="bulletin",
        source_id=10,
        source_date=date(2026, 1, 15),
        category="Sovraffollamento",
        content="La situazione di sovraffollamento nel Lazio è insostenibile.",
        created_at=datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC),
    )
    comment2 = EditorialComment(
        id=2,
        source_type="newsletter",
        source_id=20,
        source_date=date(2026, 1, 20),
        category="Suicidi",
        content="Drammatico picco di suicidi a Canton Mombello.",
        created_at=datetime(2026, 1, 20, 12, 0, 0, tzinfo=UTC),
    )
    return [(comment1, 0.85), (comment2, 0.72)]


@pytest.mark.anyio
async def test_retrieve_historical_context_async(sample_editorial_comments):
    """Test retrieving historical context asynchronously using mock repositories."""
    # Mock embedding service
    mock_embed_svc = MagicMock()
    mock_embed_svc.generate_embedding = AsyncMock(return_value=[0.1] * 768)
    
    # Mock editorial repository
    with patch("behind_bars_pulse.services.rag_service.EditorialCommentRepository") as mock_repo_class:
        mock_repo = AsyncMock()
        mock_repo.search_by_embedding.return_value = (sample_editorial_comments, 2)
        mock_repo_class.return_value = mock_repo
        
        # Instantiate service
        session = AsyncMock(spec=AsyncSession)
        rag_service = RAGService(embedding_service=mock_embed_svc)
        
        # Retrieve context
        context = await rag_service.retrieve_historical_context(
            session=session,
            query_text="sovraffollamento e suicidi nelle carceri",
        )
        
        # Verify calls and formatting
        mock_embed_svc.generate_embedding.assert_called_once_with("sovraffollamento e suicidi nelle carceri")
        mock_repo.search_by_embedding.assert_called_once()
        
        assert "### 📚 CONTESTO STORICO ED EDITORIALE RILEVANTE" in context
        assert "Da Bollettino Quotidiano del 15/01/2026 nella categoria 'Sovraffollamento' (Rilevanza Semantica: 85.0%):" in context
        assert "La situazione di sovraffollamento nel Lazio è insostenibile." in context
        assert "Da Newsletter Settimanale del 20/01/2026 nella categoria 'Suicidi' (Rilevanza Semantica: 72.0%):" in context
        assert "Drammatico picco di suicidi a Canton Mombello." in context


def test_retrieve_historical_context_sync(sample_editorial_comments):
    """Test retrieving historical context synchronously with mocked engine/session."""
    # Mock embedding service
    mock_embed_svc = MagicMock()
    mock_embed_svc._embed_query.return_value = [0.1] * 768
    
    # Mock settings and database engine/session
    with (
        patch("behind_bars_pulse.services.rag_service.create_engine") as mock_create_engine,
        patch("behind_bars_pulse.services.rag_service.Session") as mock_session_class,
    ):
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session
        
        # Mock database query output
        # Results inside engine query are list of tuples: (EditorialComment, similarity)
        mock_row1 = MagicMock()
        mock_row1.__getitem__.side_effect = lambda idx: sample_editorial_comments[0][0] if idx == 0 else 0.85
        mock_row2 = MagicMock()
        mock_row2.__getitem__.side_effect = lambda idx: sample_editorial_comments[1][0] if idx == 0 else 0.72
        
        mock_session.execute.return_value.all.return_value = [mock_row1, mock_row2]
        
        # Instantiate service and run sync retrieval
        rag_service = RAGService(embedding_service=mock_embed_svc)
        context = rag_service.retrieve_historical_context_sync(
            query_text="carceri affollate",
        )
        
        mock_embed_svc._embed_query.assert_called_once_with("carceri affollate")
        mock_session.execute.assert_called_once()
        
        assert "### 📚 CONTESTO STORICO ED EDITORIALE RILEVANTE" in context
        assert "Da Bollettino Quotidiano del 15/01/2026 nella categoria 'Sovraffollamento' (Rilevanza Semantica: 85.0%):" in context
        assert "La situazione di sovraffollamento nel Lazio è insostenibile." in context


def test_retrieve_historical_context_empty():
    """Test retrieval when database has no relevant historical results."""
    mock_embed_svc = MagicMock()
    mock_embed_svc._embed_query.return_value = [0.1] * 768
    
    with (
        patch("behind_bars_pulse.services.rag_service.create_engine"),
        patch("behind_bars_pulse.services.rag_service.Session") as mock_session_class,
    ):
        mock_session = MagicMock()
        mock_session_class.return_value.__enter__.return_value = mock_session
        mock_session.execute.return_value.all.return_value = []  # No matches
        
        rag_service = RAGService(embedding_service=mock_embed_svc)
        context = rag_service.retrieve_historical_context_sync("nonexistent theme")
        
        assert context == ""
