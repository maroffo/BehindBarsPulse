# ABOUTME: RAG service for retrieving historical context using embeddings.
# ABOUTME: Connects pgvector similarity search with bulletin and newsletter pipelines.

import asyncio
import structlog
from datetime import date
from typing import Any

from sqlalchemy import select, create_engine
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from behind_bars_pulse.config import get_settings, make_sync_url
from behind_bars_pulse.db.models import EditorialComment
from behind_bars_pulse.db.repository import EditorialCommentRepository
from behind_bars_pulse.services.embedding_service import EmbeddingService

log = structlog.get_logger()


class RAGService:
    """Service to perform Retrieval-Augmented Generation (RAG) over historical editorials."""

    def __init__(self, embedding_service: EmbeddingService | None = None) -> None:
        self.embedding_service = embedding_service or EmbeddingService()
        self.settings = get_settings()

    async def retrieve_historical_context(
        self,
        session: AsyncSession,
        query_text: str,
        limit: int = 3,
        threshold: float = 0.45,
    ) -> str:
        """Asynchronously retrieve relevant historical editorial context.

        Args:
            session: Active AsyncSession.
            query_text: The search text (e.g., summary of today's articles).
            limit: Maximum number of historical comments to retrieve.
            threshold: Similarity threshold (0-1).

        Returns:
            A formatted markdown string representing the historical context,
            or an empty string if no context is found.
        """
        log.info("retrieving_rag_context_async", query_preview=query_text[:60])
        
        try:
            # Generate embedding for the query
            query_embedding = await self.embedding_service.generate_embedding(query_text)
            
            # Query the editorial comments repository
            repo = EditorialCommentRepository(session)
            similar_comments_with_scores, _ = await repo.search_by_embedding(
                embedding=query_embedding,
                threshold=threshold,
                limit=limit,
            )
            
            if not similar_comments_with_scores:
                log.info("rag_context_empty")
                return ""

            return self._format_context(similar_comments_with_scores)
            
        except Exception as e:
            log.exception("rag_retrieval_async_failed", error=str(e))
            return ""

    def retrieve_historical_context_sync(
        self,
        query_text: str,
        limit: int = 3,
        threshold: float = 0.45,
    ) -> str:
        """Synchronously retrieve relevant historical editorial context.

        Perfect for synchronous workflows like the daily BulletinGenerator pipeline.

        Args:
            query_text: The search text (e.g., summary of today's articles).
            limit: Maximum number of historical comments to retrieve.
            threshold: Similarity threshold (0-1).

        Returns:
            A formatted markdown string representing the historical context,
            or an empty string if no context is found.
        """
        log.info("retrieving_rag_context_sync", query_preview=query_text[:60])
        
        if not self.settings.database_url:
            log.warning("no_database_url_configured_for_rag")
            return ""

        try:
            # Generate embedding synchronously using the synchronous _embed_query method
            query_embedding = self.embedding_service._embed_query(query_text)
            
            # Query the DB using sync SQLAlchemy engine
            sync_url = make_sync_url(self.settings.database_url)
            engine = create_engine(sync_url)
            
            with Session(engine) as session:
                distance = EditorialComment.embedding.cosine_distance(query_embedding)
                similarity = (1 - distance).label("similarity")
                
                results = session.execute(
                    select(EditorialComment, similarity)
                    .where(EditorialComment.embedding.isnot(None))
                    .where((1 - distance) >= threshold)
                    .order_by(distance)
                    .limit(limit)
                ).all()
                
                if not results:
                    log.info("rag_context_empty")
                    return ""
                
                # Convert results tuple (comment, similarity) to match repo structure
                similar_comments_with_scores = [(row[0], float(row[1])) for row in results]
                return self._format_context(similar_comments_with_scores)
                
        except Exception as e:
            log.exception("rag_retrieval_sync_failed", error=str(e))
            return ""

    def _format_context(self, items: list[tuple[EditorialComment, float]]) -> str:
        """Format the retrieved comments into a structured markdown block."""
        blocks = []
        blocks.append("---")
        blocks.append("### 📚 CONTESTO STORICO ED EDITORIALE RILEVANTE")
        blocks.append(
            "I seguenti estratti provengono da editoriali e newsletter precedenti. "
            "Usali per tessere collegamenti storici, mostrare la continuazione di trend, "
            "o fare riferimento a notizie passate se pertinente:\n"
        )
        
        for comment, score in items:
            source_label = "Bollettino Quotidiano" if comment.source_type == "bulletin" else "Newsletter Settimanale"
            date_str = comment.source_date.strftime("%d/%m/%Y")
            category_str = f" nella categoria '{comment.category}'" if comment.category else ""
            
            blocks.append(f"**Da {source_label} del {date_str}{category_str} (Rilevanza Semantica: {score:.1%}):**")
            # Indent content slightly for readability
            indented_content = "\n".join(f"> {line}" for line in comment.content.strip().split("\n"))
            blocks.append(indented_content)
            blocks.append("")  # Blank line separator
            
        blocks.append("---")
        return "\n".join(blocks)
