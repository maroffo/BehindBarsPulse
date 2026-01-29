# ABOUTME: Tests for narrative storage layer.
# ABOUTME: Validates JSON persistence and article collection handling.

from datetime import date, timedelta
from pathlib import Path

import pytest

from behind_bars_pulse.config import Settings
from behind_bars_pulse.models import EnrichedArticle
from behind_bars_pulse.narrative.models import NarrativeContext, StoryThread
from behind_bars_pulse.narrative.storage import NarrativeStorage


@pytest.fixture
def storage_settings(tmp_path: Path, mock_settings: Settings) -> Settings:
    """Create settings with temp data directory."""
    return Settings(
        gcp_project=mock_settings.gcp_project,
        gcp_location=mock_settings.gcp_location,
        gemini_model=mock_settings.gemini_model,
        gemini_fallback_model=mock_settings.gemini_fallback_model,
        ai_sleep_between_calls=0,
        feed_url=mock_settings.feed_url,
        feed_timeout=mock_settings.feed_timeout,
        max_articles=mock_settings.max_articles,
        smtp_host=mock_settings.smtp_host,
        smtp_port=mock_settings.smtp_port,
        ses_usr=mock_settings.ses_usr,
        ses_pwd=mock_settings.ses_pwd,
        sender_email=mock_settings.sender_email,
        sender_name=mock_settings.sender_name,
        bounce_email=mock_settings.bounce_email,
        default_recipient=mock_settings.default_recipient,
        previous_issues_dir=mock_settings.previous_issues_dir,
        templates_dir=mock_settings.templates_dir,
        data_dir=tmp_path / "data",
        story_archive_days=30,
        weekly_lookback_days=7,
    )


@pytest.fixture
def storage(storage_settings: Settings) -> NarrativeStorage:
    """Create NarrativeStorage with test settings."""
    return NarrativeStorage(storage_settings)


@pytest.fixture
def sample_context() -> NarrativeContext:
    """Create sample narrative context."""
    return NarrativeContext(
        ongoing_storylines=[
            StoryThread(
                id="story-001",
                topic="Test Story",
                first_seen=date(2025, 1, 1),
                last_update=date(2025, 1, 10),
                summary="Test summary.",
                keywords=["test", "story"],
            ),
        ],
        editorial_tone="Test tone",
    )


class TestNarrativeStorage:
    """Tests for NarrativeStorage."""

    def test_creates_data_directory(self, storage: NarrativeStorage) -> None:
        """Storage creates data directory on init."""
        assert storage.settings.data_dir.exists()
        assert (storage.settings.data_dir / "collected_articles").exists()

    def test_load_context_returns_empty_when_missing(self, storage: NarrativeStorage) -> None:
        """load_context returns empty context when file doesn't exist."""
        ctx = storage.load_context()
        assert isinstance(ctx, NarrativeContext)
        assert len(ctx.ongoing_storylines) == 0

    def test_save_and_load_context(
        self,
        storage: NarrativeStorage,
        sample_context: NarrativeContext,
    ) -> None:
        """Context can be saved and loaded."""
        storage.save_context(sample_context)

        assert storage.context_path.exists()

        loaded = storage.load_context()
        assert len(loaded.ongoing_storylines) == 1
        assert loaded.ongoing_storylines[0].id == "story-001"
        assert loaded.ongoing_storylines[0].topic == "Test Story"

    def test_save_updates_last_updated(
        self,
        storage: NarrativeStorage,
        sample_context: NarrativeContext,
    ) -> None:
        """Saving context updates last_updated timestamp."""
        original_time = sample_context.last_updated
        storage.save_context(sample_context)

        loaded = storage.load_context()
        assert loaded.last_updated >= original_time

    def test_archive_old_stories(self, storage: NarrativeStorage) -> None:
        """Stories without recent updates are marked dormant."""
        old_date = date.today() - timedelta(days=60)
        recent_date = date.today() - timedelta(days=5)

        context = NarrativeContext(
            ongoing_storylines=[
                StoryThread(
                    id="old-story",
                    topic="Old Story",
                    status="active",
                    first_seen=old_date - timedelta(days=30),
                    last_update=old_date,
                    summary="Old story.",
                ),
                StoryThread(
                    id="recent-story",
                    topic="Recent Story",
                    status="active",
                    first_seen=recent_date - timedelta(days=10),
                    last_update=recent_date,
                    summary="Recent story.",
                ),
            ],
        )

        archived_count = storage.archive_old_stories(context)

        assert archived_count == 1
        old_story = context.get_story_by_id("old-story")
        assert old_story is not None
        assert old_story.status == "dormant"

        recent_story = context.get_story_by_id("recent-story")
        assert recent_story is not None
        assert recent_story.status == "active"


class TestCollectedArticles:
    """Tests for article collection storage."""

    @pytest.fixture
    def sample_articles(self) -> dict[str, EnrichedArticle]:
        """Create sample articles."""
        return {
            "https://example.com/article1": EnrichedArticle(
                title="Test Article 1",
                link="https://example.com/article1",
                content="Test content 1",
                author="Author 1",
                source="Source 1",
                summary="Summary 1",
            ),
            "https://example.com/article2": EnrichedArticle(
                title="Test Article 2",
                link="https://example.com/article2",
                content="Test content 2",
                author="Author 2",
                source="Source 2",
                summary="Summary 2",
            ),
        }

    def test_save_collected_articles(
        self,
        storage: NarrativeStorage,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """Articles can be saved to dated file."""
        collection_date = date(2025, 1, 15)
        file_path = storage.save_collected_articles(sample_articles, collection_date)

        assert file_path.exists()
        assert file_path.name == "2025-01-15.json"

    def test_load_collected_articles(
        self,
        storage: NarrativeStorage,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """Saved articles can be loaded back."""
        collection_date = date(2025, 1, 15)
        storage.save_collected_articles(sample_articles, collection_date)

        loaded = storage.load_collected_articles(collection_date)

        assert len(loaded) == 2
        assert "https://example.com/article1" in loaded
        assert loaded["https://example.com/article1"].title == "Test Article 1"

    def test_load_nonexistent_collection(self, storage: NarrativeStorage) -> None:
        """Loading nonexistent collection returns empty dict."""
        loaded = storage.load_collected_articles(date(2020, 1, 1))
        assert loaded == {}

    def test_get_available_collection_dates(
        self,
        storage: NarrativeStorage,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """Available collection dates are returned sorted."""
        storage.save_collected_articles(sample_articles, date(2025, 1, 10))
        storage.save_collected_articles(sample_articles, date(2025, 1, 15))
        storage.save_collected_articles(sample_articles, date(2025, 1, 12))

        dates = storage.get_available_collection_dates()

        assert len(dates) == 3
        assert dates[0] == date(2025, 1, 10)
        assert dates[1] == date(2025, 1, 12)
        assert dates[2] == date(2025, 1, 15)

    def test_get_recent_collection_dates(
        self,
        storage: NarrativeStorage,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """Recent collection dates within lookback period."""
        today = date.today()
        old_date = today - timedelta(days=30)
        recent_date = today - timedelta(days=3)

        storage.save_collected_articles(sample_articles, old_date)
        storage.save_collected_articles(sample_articles, recent_date)

        recent = storage.get_recent_collection_dates(days=7)

        assert len(recent) == 1
        assert recent[0] == recent_date

    def test_cleanup_old_collections(
        self,
        storage: NarrativeStorage,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """Old collections are removed by cleanup."""
        today = date.today()
        old_date = today - timedelta(days=60)
        recent_date = today - timedelta(days=5)

        storage.save_collected_articles(sample_articles, old_date)
        storage.save_collected_articles(sample_articles, recent_date)

        removed = storage.cleanup_old_collections(keep_days=30)

        assert removed == 1

        dates = storage.get_available_collection_dates()
        assert len(dates) == 1
        assert dates[0] == recent_date
