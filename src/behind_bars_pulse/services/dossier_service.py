# ABOUTME: Orchestrates generation and file-based caching of facility monographs.
# ABOUTME: Fetches historical DB data, performs RAG query, and runs Gemini.

import json
import os
import structlog
from datetime import datetime, date, UTC, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from behind_bars_pulse.ai.service import AIService
from behind_bars_pulse.config import get_settings
from behind_bars_pulse.db.models import FacilitySnapshot, PrisonEvent
from behind_bars_pulse.services.rag_service import RAGService

log = structlog.get_logger()


class FacilityDossierService:
    """Service for managing, caching, and generating in-depth dossiers for prison facilities."""

    def __init__(self, ai_service: AIService | None = None) -> None:
        self.settings = get_settings()
        self.ai_service = ai_service or AIService(self.settings)
        self.rag_service = RAGService()
        
        # Define cache directory inside project data folder
        self.cache_dir = Path(self.settings.templates_dir).parent / "data" / "dossiers"

    def _get_cache_path(self, facility_name: str) -> Path:
        """Get the filesystem path for a cached dossier."""
        # Sanitize filename: replace spaces/slashes with underscores
        safe_name = facility_name.lower().replace(" ", "_").replace("/", "_").replace("\\", "_")
        return self.cache_dir / f"{safe_name}.json"

    def get_cached_dossier(self, facility_name: str, max_age_days: int = 7) -> str | None:
        """Retrieve a cached dossier if it exists and is not too old.

        Args:
            facility_name: The name of the facility.
            max_age_days: Max age in days before considering the cache stale.

        Returns:
            The dossier Markdown string, or None if expired/not found.
        """
        cache_path = self._get_cache_path(facility_name)
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            generated_at_str = data.get("generated_at")
            if not generated_at_str:
                return None

            generated_at = datetime.fromisoformat(generated_at_str)
            # Ensure timezone-aware comparison
            if generated_at.tzinfo is None:
                generated_at = generated_at.replace(tzinfo=UTC)
                
            age = datetime.now(UTC) - generated_at
            if age > timedelta(days=max_age_days):
                log.info("cached_dossier_expired", facility=facility_name, age_days=age.days)
                return None

            log.info("cached_dossier_loaded", facility=facility_name)
            return data.get("content")
        except Exception as e:
            log.warning("failed_to_load_cached_dossier", facility=facility_name, error=str(e))
            return None

    def _save_to_cache(self, facility_name: str, content: str) -> None:
        """Save generated dossier to local filesystem cache."""
        try:
            # Ensure directory exists
            os.makedirs(self.cache_dir, exist_ok=True)
            cache_path = self._get_cache_path(facility_name)
            
            data = {
                "facility": facility_name,
                "generated_at": datetime.now(UTC).isoformat(),
                "content": content,
            }
            
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
            log.info("dossier_saved_to_cache", facility=facility_name, path=str(cache_path))
        except Exception as e:
            log.error("failed_to_cache_dossier", facility=facility_name, error=str(e))

    async def get_or_generate_dossier(
        self,
        session: AsyncSession,
        facility_name: str,
        force_refresh: bool = False,
    ) -> str:
        """Get a facility dossier, generating it via Gemini if not cached or expired.

        Args:
            session: Active database session.
            facility_name: Name of the facility to analyze.
            force_refresh: If True, bypasses cache and forces regeneration.

        Returns:
            The markdown string of the generated/cached dossier.
        """
        if not force_refresh:
            cached = self.get_cached_dossier(facility_name)
            if cached:
                return cached

        log.info("generating_new_dossier", facility=facility_name)

        # 1. Fetch capacity snapshots of the past 180 days for this facility
        cutoff_date = date.today() - timedelta(days=180)
        snapshots_res = await session.execute(
            select(FacilitySnapshot)
            .where(FacilitySnapshot.facility == facility_name)
            .where(FacilitySnapshot.snapshot_date >= cutoff_date)
            .order_by(FacilitySnapshot.snapshot_date.desc())
        )
        snapshots = snapshots_res.scalars().all()

        # 2. Fetch critical events of the past 180 days for this facility
        events_res = await session.execute(
            select(PrisonEvent)
            .where(PrisonEvent.facility == facility_name)
            .where(PrisonEvent.event_date >= cutoff_date)
            .order_by(PrisonEvent.event_date.desc().nulls_last())
        )
        events = events_res.scalars().all()

        # 3. Determine region (fallback to first record or "Sconosciuta")
        region = "Sconosciuta"
        if snapshots:
            region = snapshots[0].region or "Sconosciuta"
        elif events:
            region = events[0].region or "Sconosciuta"

        # 4. Fetch RAG Context: previous editorial comments mentioning this facility
        log.info("querying_rag_context_for_facility", facility=facility_name)
        rag_query = f"istituto carcere {facility_name} {region}"
        # We query previous comments mentioning the facility
        rag_context = await self.rag_service.retrieve_historical_context(
            session=session,
            query_text=rag_query,
            limit=4,
            threshold=0.35,  # Slightly lower threshold to fetch any past mentions of this specific prison
        )

        # 5. Format numerical/historical data for the Gemini Prompt
        capacity_payload = [
            {
                "date": s.snapshot_date.isoformat() if s.snapshot_date else "",
                "inmates": s.inmates,
                "capacity": s.capacity,
                "occupancy_rate": s.occupancy_rate,
            }
            for s in snapshots
        ]

        incident_payload = [
            {
                "date": e.event_date.isoformat() if e.event_date else "",
                "type": e.event_type,
                "count": e.count if e.count is not None else 1,
                "description": e.description,
            }
            for e in events
        ]

        # 6. Call AI generator
        try:
            dossier_content = self.ai_service.generate_facility_dossier(
                facility_name=facility_name,
                region=region,
                capacity_data=capacity_payload,
                incident_data=incident_payload,
                historical_comments=rag_context or "Nessun commento editoriale passato ha menzionato questo istituto.",
            )
            
            # Save the result to cache
            self._save_to_cache(facility_name, dossier_content)
            return dossier_content
        except Exception as e:
            log.exception("failed_to_generate_dossier_via_ai", facility=facility_name, error=str(e))
            # Fallback output in case of Gemini failures
            return f"# Errore di Generazione Dossier: {facility_name}\n\nSi è verificato un problema nella generazione automatica via AI. Riprova più tardi."
