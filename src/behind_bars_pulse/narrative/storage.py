# ABOUTME: JSON-based persistence for narrative memory.
# ABOUTME: Handles loading, saving, and archiving of narrative context.

from datetime import date, datetime, timedelta
from pathlib import Path

import structlog

from behind_bars_pulse.config import Settings, get_settings
from behind_bars_pulse.models import EnrichedArticle
from behind_bars_pulse.narrative.models import NarrativeContext

log = structlog.get_logger()


class NarrativeStorage:
    """Handles persistence of narrative context to JSON files."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._ensure_data_dir()

    def _ensure_data_dir(self) -> None:
        """Create data directory structure if it doesn't exist."""
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        (self.settings.data_dir / "collected_articles").mkdir(exist_ok=True)

    @property
    def context_path(self) -> Path:
        """Path to the narrative context file."""
        return self.settings.data_dir / self.settings.narrative_context_file

    @property
    def collected_articles_dir(self) -> Path:
        """Path to the collected articles directory."""
        return self.settings.data_dir / "collected_articles"

    def load_context(self) -> NarrativeContext:
        """Load narrative context from JSON file.

        Returns:
            NarrativeContext loaded from file, or empty context if file doesn't exist.
        """
        if not self.context_path.exists():
            log.info("narrative_context_not_found", path=str(self.context_path))
            return NarrativeContext()

        log.debug("loading_narrative_context", path=str(self.context_path))
        content = self.context_path.read_text(encoding="utf-8")
        context = NarrativeContext.model_validate_json(content)
        log.info(
            "narrative_context_loaded",
            stories=len(context.ongoing_storylines),
            characters=len(context.key_characters),
            followups=len(context.pending_followups),
        )
        return context

    def save_context(self, context: NarrativeContext) -> None:
        """Save narrative context to JSON file.

        Args:
            context: NarrativeContext to save.
        """
        context.last_updated = datetime.now()
        content = context.model_dump_json(indent=2)
        self.context_path.write_text(content, encoding="utf-8")
        log.info(
            "narrative_context_saved",
            path=str(self.context_path),
            stories=len(context.ongoing_storylines),
        )

    def archive_old_stories(self, context: NarrativeContext, as_of: date | None = None) -> int:
        """Mark stories without recent updates as dormant.

        Args:
            context: NarrativeContext to process.
            as_of: Reference date for age calculation. Defaults to today.

        Returns:
            Number of stories archived.
        """
        as_of = as_of or date.today()
        cutoff = as_of - timedelta(days=self.settings.story_archive_days)
        archived = 0

        for story in context.ongoing_storylines:
            if story.status == "active" and story.last_update < cutoff:
                story.status = "dormant"
                archived += 1
                log.info("story_archived", story_id=story.id, topic=story.topic)

        return archived

    def save_collected_articles(
        self,
        articles: dict[str, EnrichedArticle],
        collection_date: date | None = None,
    ) -> Path:
        """Save collected articles to a dated JSON file.

        Args:
            articles: Dictionary of URL -> EnrichedArticle.
            collection_date: Date of collection. Defaults to today.

        Returns:
            Path to the saved file.
        """
        collection_date = collection_date or date.today()
        filename = f"{collection_date.isoformat()}.json"
        file_path = self.collected_articles_dir / filename

        articles_data = {url: article.model_dump(mode="json") for url, article in articles.items()}
        import json

        file_path.write_text(
            json.dumps(articles_data, indent=2, ensure_ascii=False), encoding="utf-8"
        )

        log.info("collected_articles_saved", path=str(file_path), count=len(articles))
        return file_path

    def load_collected_articles(self, collection_date: date) -> dict[str, EnrichedArticle]:
        """Load collected articles from a dated JSON file.

        Args:
            collection_date: Date of collection to load.

        Returns:
            Dictionary of URL -> EnrichedArticle, or empty dict if file doesn't exist.
        """
        filename = f"{collection_date.isoformat()}.json"
        file_path = self.collected_articles_dir / filename

        if not file_path.exists():
            log.warning("collected_articles_not_found", date=collection_date.isoformat())
            return {}

        import json

        content = json.loads(file_path.read_text(encoding="utf-8"))
        articles = {url: EnrichedArticle.model_validate(data) for url, data in content.items()}

        log.info("collected_articles_loaded", date=collection_date.isoformat(), count=len(articles))
        return articles

    def get_available_collection_dates(self) -> list[date]:
        """Get list of dates with collected articles.

        Returns:
            Sorted list of dates (oldest first).
        """
        dates = []
        for file_path in self.collected_articles_dir.glob("*.json"):
            try:
                date_str = file_path.stem
                dates.append(date.fromisoformat(date_str))
            except ValueError:
                continue

        return sorted(dates)

    def get_recent_collection_dates(self, days: int | None = None) -> list[date]:
        """Get dates with collections in the recent past.

        Args:
            days: Number of days to look back. Defaults to settings value.

        Returns:
            List of dates with collections within the lookback period (oldest first).
        """
        days = days or self.settings.weekly_lookback_days
        cutoff = date.today() - timedelta(days=days)
        return [d for d in self.get_available_collection_dates() if d >= cutoff]

    def cleanup_old_collections(self, keep_days: int | None = None) -> int:
        """Remove collected articles older than the specified age.

        Args:
            keep_days: Number of days to keep. Defaults to story_archive_days.

        Returns:
            Number of files removed.
        """
        keep_days = keep_days or self.settings.story_archive_days
        cutoff = date.today() - timedelta(days=keep_days)
        removed = 0

        for file_path in self.collected_articles_dir.glob("*.json"):
            try:
                file_date = date.fromisoformat(file_path.stem)
                if file_date < cutoff:
                    file_path.unlink()
                    removed += 1
                    log.debug("old_collection_removed", path=str(file_path))
            except ValueError:
                continue

        if removed:
            log.info("old_collections_cleaned", removed=removed)

        return removed
