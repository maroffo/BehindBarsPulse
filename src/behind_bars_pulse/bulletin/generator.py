# ABOUTME: Bulletin generator for daily editorial commentary.
# ABOUTME: Orchestrates article loading, AI generation, and DB persistence.

from datetime import date, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from behind_bars_pulse.ai.service import AIService
from behind_bars_pulse.bulletin.models import Bulletin, EditorialCommentChunk
from behind_bars_pulse.config import Settings, get_settings
from behind_bars_pulse.db.models import Article as ArticleORM
from behind_bars_pulse.models import EnrichedArticle

if TYPE_CHECKING:
    from behind_bars_pulse.models import Article

log = structlog.get_logger()


class BulletinGenerator:
    """Generator for daily editorial bulletins on prison news."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.ai_service = AIService(self.settings)

    def generate(self, issue_date: date | None = None) -> Bulletin | None:
        """Generate a bulletin for the given date.

        Args:
            issue_date: Date for the bulletin. Defaults to today.
                        Analyzes articles from the day before.

        Returns:
            Generated Bulletin, or None if no articles found.
        """
        issue_date = issue_date or date.today()
        articles_date = issue_date - timedelta(days=1)

        log.info("generating_bulletin", issue_date=issue_date, articles_date=articles_date)

        # Load articles from the day before
        articles = self._load_articles_from_db(articles_date)

        if not articles:
            log.warning("no_articles_for_bulletin", date=articles_date)
            return None

        # Retrieve historical RAG context first
        try:
            from behind_bars_pulse.services.rag_service import RAGService
            rag_service = RAGService()
            query_text = " ".join([a.title for a in articles.values()])
            historical_context = rag_service.retrieve_historical_context_sync(query_text)
        except Exception as e:
            log.warning("rag_context_generation_failed", error=str(e))
            historical_context = None

        # Check for active statistical anomalies (Early Warning) for the facilities in today's articles
        active_alerts = []
        try:
            from behind_bars_pulse.services.analytics_service import AnalyticsService
            analytics_svc = AnalyticsService()
            anomalies = analytics_svc.calculate_facility_anomalies_sync()
            
            # Create a set of today's facility names
            today_facilities = {a.author for a in articles.values() if a.author} | {a.title for a in articles.values() if a.title}
            # Actually we can just search if facility name is a substring of the title or content
            # Or if enriched articles have facility name defined (EnrichedArticle doesn't have facility, but we can search for facility name in content!)
            for a in anomalies:
                facility_name = a["facility"]
                # Check if the facility name is mentioned in any of today's articles (title or content)
                mentioned = False
                for art in articles.values():
                    text_to_search = f"{art.title} {art.content}".lower()
                    if facility_name.lower() in text_to_search:
                        mentioned = True
                        break
                
                if mentioned and a["is_anomaly"] and a["severity"] in ["Alta", "Critica"]:
                    alert_msg = (
                        f"- ⚠️ ALLERTA STATISTICA CRITICA per l'istituto '{facility_name}': "
                        f"Il nostro sistema ha rilevato un picco anomalo degli incidenti negli ultimi 30 giorni. "
                        f"Ci sono stati ben {a['active_count']} incidenti (Z-score: {a['z_score']}), "
                        f"a fronte di una media storica pregressa di appena {a['baseline_monthly_rate']:.1f}/mese."
                    )
                    active_alerts.append(alert_msg)
        except Exception as e:
            log.warning("failed_to_calculate_early_warning_alerts", error=str(e))

        # Prepend active statistical alerts to the RAG historical context
        if active_alerts:
            alerts_block = (
                "### 🚨 ALLERTE DI CRISI STATISTICHE ATTIVE (EARLY WARNING)\n"
                "I seguenti istituti citati nelle notizie di oggi registrano un incremento anomalo degli incidenti negli ultimi 30 giorni. "
                "Fai riferimento a questi dati oggettivi nel tuo commento editoriale per evidenziare la gravità e la continuità della crisi in queste strutture:\n"
                + "\n".join(active_alerts)
                + "\n\n"
            )
            if historical_context:
                historical_context = alerts_block + historical_context
            else:
                historical_context = alerts_block

        # Generate bulletin content via AI
        bulletin_content = self.ai_service.generate_bulletin(
            articles=articles,
            issue_date=issue_date.isoformat(),
            historical_context=historical_context,
        )

        # Generate press review with thematic categories (like newsletter)
        press_review = self.ai_service.generate_press_review(
            articles={url: self._to_article(a) for url, a in articles.items()}
        )
        press_review_data = [cat.model_dump(mode="json") for cat in press_review]

        return Bulletin(
            issue_date=issue_date,
            title=bulletin_content.title,
            subtitle=bulletin_content.subtitle,
            content=bulletin_content.content,
            key_topics=bulletin_content.key_topics,
            sources_cited=bulletin_content.sources_cited,
            articles_count=len(articles),
            press_review=press_review_data,
        )

    def _to_article(self, enriched: EnrichedArticle) -> "Article":
        """Convert EnrichedArticle to Article for press review generation."""
        from behind_bars_pulse.models import Article

        return Article(
            title=enriched.title,
            link=enriched.link,
            content=enriched.content,
            published_date=enriched.published_date,
        )

    def _load_articles_from_db(self, articles_date: date) -> dict[str, EnrichedArticle]:
        """Load articles from database for a specific date.

        Args:
            articles_date: Date to load articles for.

        Returns:
            Dictionary mapping URLs to EnrichedArticle objects.
        """
        if not self.settings.database_url:
            log.warning("no_database_url_configured")
            return {}

        # Use sync connection to avoid event loop issues
        from behind_bars_pulse.config import make_sync_url

        sync_url = make_sync_url(self.settings.database_url)

        try:
            engine = create_engine(sync_url)
            with Session(engine) as session:
                db_articles = (
                    session.query(ArticleORM)
                    .filter(ArticleORM.published_date == articles_date)
                    .all()
                )

                articles = {}
                for db_article in db_articles:
                    articles[db_article.link] = EnrichedArticle(
                        title=db_article.title,
                        link=db_article.link,
                        content=db_article.content,
                        author=db_article.author or "",
                        source=db_article.source or "",
                        summary=db_article.summary or "",
                        published_date=db_article.published_date,
                    )

                log.info("loaded_articles_from_db", count=len(articles), date=articles_date)
                return articles

        except Exception as e:
            log.error("db_load_failed", error=str(e))
            return {}

    def extract_editorial_comments(
        self,
        bulletin: Bulletin,
        bulletin_id: int,
    ) -> list[EditorialCommentChunk]:
        """Extract searchable comment chunks from a bulletin.

        Splits the bulletin content into logical chunks for semantic search.

        Args:
            bulletin: The bulletin to extract from.
            bulletin_id: Database ID of the saved bulletin.

        Returns:
            List of EditorialCommentChunk objects.
        """
        chunks = []

        # Extract the main content as one chunk
        if bulletin.content:
            chunks.append(
                EditorialCommentChunk(
                    source_type="bulletin",
                    source_id=bulletin_id,
                    source_date=bulletin.issue_date,
                    category=None,
                    content=bulletin.content,
                )
            )

        # If content has clear paragraph breaks, split into separate chunks
        paragraphs = [p.strip() for p in bulletin.content.split("\n\n") if p.strip()]
        if len(paragraphs) > 2:
            # Reset and use paragraphs as chunks instead
            chunks = []
            for i, para in enumerate(paragraphs):
                if len(para) > 100:
                    chunks.append(
                        EditorialCommentChunk(
                            source_type="bulletin",
                            source_id=bulletin_id,
                            source_date=bulletin.issue_date,
                            category=f"paragraph_{i + 1}",
                            content=para,
                        )
                    )

        log.info("extracted_editorial_comments", count=len(chunks), bulletin_id=bulletin_id)
        return chunks
