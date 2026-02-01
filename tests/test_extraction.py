# ABOUTME: Tests for AI story/entity/followup extraction methods.
# ABOUTME: Validates extraction logic with mocked AI responses.

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from behind_bars_pulse.ai.service import AIService
from behind_bars_pulse.collector import ArticleCollector
from behind_bars_pulse.config import Settings
from behind_bars_pulse.models import EnrichedArticle
from behind_bars_pulse.narrative.models import (
    NarrativeContext,
    StoryThread,
)


@pytest.fixture
def extraction_settings(tmp_path: Path) -> Settings:
    """Create settings for extraction testing."""
    return Settings(
        gemini_api_key=SecretStr("test-api-key"),
        gemini_model="gemini-test",
        gemini_fallback_model="gemini-fallback",
        ai_sleep_between_calls=0,
        feed_url="https://example.com/feed.rss",
        feed_timeout=5,
        max_articles=10,
        smtp_host="localhost",
        smtp_port=1025,
        ses_usr=SecretStr("test-user"),
        ses_pwd=SecretStr("test-password"),
        sender_email="test@example.com",
        sender_name="Test Sender",
        bounce_email="bounce@example.com",
        default_recipient="recipient@example.com",
        previous_issues_dir=tmp_path / "previous_issues",
        templates_dir=Path("src/behind_bars_pulse/email/templates"),
        data_dir=tmp_path / "data",
    )


@pytest.fixture
def sample_articles() -> dict[str, EnrichedArticle]:
    """Create sample enriched articles."""
    return {
        "https://example.com/1": EnrichedArticle(
            title="Decreto Carceri: nuovi sviluppi in Senato",
            link="https://example.com/1",
            content="Il Ministro Nordio ha annunciato modifiche al decreto...",
            author="Test Author",
            source="Test Source",
            summary="Sviluppi sul decreto carceri.",
        ),
    }


class TestAIServiceExtraction:
    """Tests for AIService extraction methods."""

    @patch.object(AIService, "_generate")
    def test_extract_stories_new_story(
        self,
        mock_generate: MagicMock,
        extraction_settings: Settings,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """extract_stories identifies new stories."""
        mock_generate.return_value = """{
            "updated_stories": [],
            "new_stories": [
                {
                    "topic": "Decreto Carceri",
                    "summary": "Ongoing reform discussion.",
                    "keywords": ["decreto", "carceri", "riforma"],
                    "impact_score": 0.7,
                    "article_urls": ["https://example.com/1"]
                }
            ]
        }"""

        service = AIService(extraction_settings)
        result = service.extract_stories(sample_articles, [])

        assert len(result["new_stories"]) == 1
        assert result["new_stories"][0]["topic"] == "Decreto Carceri"

    @patch.object(AIService, "_generate")
    def test_extract_stories_update_existing(
        self,
        mock_generate: MagicMock,
        extraction_settings: Settings,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """extract_stories updates existing stories."""
        mock_generate.return_value = """{
            "updated_stories": [
                {
                    "id": "story-001",
                    "new_summary": "Updated summary with new developments.",
                    "new_keywords": ["senato"],
                    "impact_score": 0.8,
                    "article_urls": ["https://example.com/1"]
                }
            ],
            "new_stories": []
        }"""

        existing = [{"id": "story-001", "topic": "Decreto", "summary": "Old", "keywords": []}]
        service = AIService(extraction_settings)
        result = service.extract_stories(sample_articles, existing)

        assert len(result["updated_stories"]) == 1
        assert result["updated_stories"][0]["id"] == "story-001"

    @patch.object(AIService, "_generate")
    def test_extract_entities_new_character(
        self,
        mock_generate: MagicMock,
        extraction_settings: Settings,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """extract_entities identifies new characters."""
        mock_generate.return_value = """{
            "updated_characters": [],
            "new_characters": [
                {
                    "name": "Carlo Nordio",
                    "role": "Ministro della Giustizia",
                    "aliases": ["Ministro Nordio"],
                    "initial_position": {
                        "stance": "Il decreto è necessario.",
                        "source_url": "https://example.com/1"
                    }
                }
            ]
        }"""

        service = AIService(extraction_settings)
        result = service.extract_entities(sample_articles, [])

        assert len(result["new_characters"]) == 1
        assert result["new_characters"][0]["name"] == "Carlo Nordio"

    @patch.object(AIService, "_generate")
    def test_detect_followups(
        self,
        mock_generate: MagicMock,
        extraction_settings: Settings,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """detect_followups identifies upcoming events."""
        mock_generate.return_value = """{
            "followups": [
                {
                    "event": "Voto finale Senato sul Decreto Carceri",
                    "expected_date": "2025-02-15",
                    "story_id": "story-001",
                    "source_url": "https://example.com/1"
                }
            ]
        }"""

        service = AIService(extraction_settings)
        result = service.detect_followups(sample_articles, ["story-001"])

        assert len(result["followups"]) == 1
        assert result["followups"][0]["event"] == "Voto finale Senato sul Decreto Carceri"


class TestCollectorNarrativeUpdate:
    """Tests for collector narrative context updates."""

    @patch("behind_bars_pulse.collector.AIService")
    @patch("behind_bars_pulse.collector.FeedFetcher")
    def test_collect_updates_narrative_context(
        self,
        mock_fetcher_class: MagicMock,
        mock_ai_class: MagicMock,
        extraction_settings: Settings,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """Collect updates narrative context with stories."""
        from behind_bars_pulse.models import Article

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_feed.return_value = {
            "https://example.com/1": Article(
                title="Test",
                link="https://example.com/1",
                content="Content",
            )
        }
        mock_fetcher_class.return_value = mock_fetcher

        mock_ai = MagicMock()
        mock_ai.enrich_articles.return_value = sample_articles
        mock_ai.extract_stories.return_value = {
            "updated_stories": [],
            "new_stories": [
                {
                    "topic": "Test Story",
                    "summary": "Test summary",
                    "keywords": ["test"],
                    "impact_score": 0.5,
                    "article_urls": [],
                }
            ],
        }
        mock_ai.extract_entities.return_value = {
            "updated_characters": [],
            "new_characters": [],
        }
        mock_ai.detect_followups.return_value = {"followups": []}
        mock_ai_class.return_value = mock_ai

        collector = ArticleCollector(extraction_settings)
        collector.collect(date(2025, 1, 15))

        # Verify context was saved
        context_file = extraction_settings.data_dir / "narrative_context.json"
        assert context_file.exists()

    @patch("behind_bars_pulse.collector.AIService")
    @patch("behind_bars_pulse.collector.FeedFetcher")
    def test_collect_skip_narrative_update(
        self,
        mock_fetcher_class: MagicMock,
        mock_ai_class: MagicMock,
        extraction_settings: Settings,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """Collect can skip narrative update."""
        from behind_bars_pulse.models import Article

        mock_fetcher = MagicMock()
        mock_fetcher.fetch_feed.return_value = {
            "https://example.com/1": Article(
                title="Test",
                link="https://example.com/1",
                content="Content",
            )
        }
        mock_fetcher_class.return_value = mock_fetcher

        mock_ai = MagicMock()
        mock_ai.enrich_articles.return_value = sample_articles
        mock_ai_class.return_value = mock_ai

        collector = ArticleCollector(extraction_settings)
        collector.collect(date(2025, 1, 15), update_narrative=False)

        # Verify extraction methods were not called
        mock_ai.extract_stories.assert_not_called()
        mock_ai.extract_entities.assert_not_called()

    def test_extract_and_update_stories_creates_new(
        self,
        extraction_settings: Settings,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """_extract_and_update_stories adds new stories to context."""
        context = NarrativeContext()

        with patch.object(AIService, "extract_stories") as mock_extract:
            mock_extract.return_value = {
                "updated_stories": [],
                "new_stories": [
                    {
                        "topic": "New Story",
                        "summary": "Summary",
                        "keywords": ["keyword"],
                        "impact_score": 0.6,
                        "article_urls": ["https://example.com/1"],
                    }
                ],
            }

            collector = ArticleCollector(extraction_settings)
            collector._extract_and_update_stories(sample_articles, context, date(2025, 1, 15))

        assert len(context.ongoing_storylines) == 1
        assert context.ongoing_storylines[0].topic == "New Story"

    def test_extract_and_update_stories_updates_existing(
        self,
        extraction_settings: Settings,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """_extract_and_update_stories updates existing stories."""
        existing_story = StoryThread(
            id="story-001",
            topic="Existing Story",
            first_seen=date(2025, 1, 1),
            last_update=date(2025, 1, 10),
            summary="Old summary",
            keywords=["old"],
            mention_count=2,
        )
        context = NarrativeContext(ongoing_storylines=[existing_story])

        with patch.object(AIService, "extract_stories") as mock_extract:
            mock_extract.return_value = {
                "updated_stories": [
                    {
                        "id": "story-001",
                        "new_summary": "Updated summary",
                        "new_keywords": ["new"],
                        "impact_score": 0.8,
                        "article_urls": ["https://example.com/1"],
                    }
                ],
                "new_stories": [],
            }

            collector = ArticleCollector(extraction_settings)
            collector._extract_and_update_stories(sample_articles, context, date(2025, 1, 15))

        assert len(context.ongoing_storylines) == 1
        updated = context.ongoing_storylines[0]
        assert updated.summary == "Updated summary"
        assert updated.mention_count == 3
        assert "new" in updated.keywords
        assert updated.last_update == date(2025, 1, 15)

    def test_extract_and_update_characters_creates_new(
        self,
        extraction_settings: Settings,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """_extract_and_update_characters adds new characters."""
        context = NarrativeContext()

        with patch.object(AIService, "extract_entities") as mock_extract:
            mock_extract.return_value = {
                "updated_characters": [],
                "new_characters": [
                    {
                        "name": "Test Person",
                        "role": "Test Role",
                        "aliases": ["TP"],
                        "initial_position": {
                            "stance": "Test stance",
                            "source_url": "https://example.com/1",
                        },
                    }
                ],
            }

            collector = ArticleCollector(extraction_settings)
            collector._extract_and_update_characters(sample_articles, context, date(2025, 1, 15))

        assert len(context.key_characters) == 1
        assert context.key_characters[0].name == "Test Person"
        assert len(context.key_characters[0].positions) == 1

    def test_detect_and_add_followups(
        self,
        extraction_settings: Settings,
        sample_articles: dict[str, EnrichedArticle],
    ) -> None:
        """_detect_and_add_followups adds followups to context."""
        context = NarrativeContext(
            ongoing_storylines=[
                StoryThread(
                    id="story-001",
                    topic="Test",
                    first_seen=date(2025, 1, 1),
                    last_update=date(2025, 1, 10),
                    summary="Test",
                )
            ]
        )

        with patch.object(AIService, "detect_followups") as mock_detect:
            mock_detect.return_value = {
                "followups": [
                    {
                        "event": "Test Event",
                        "expected_date": "2025-02-01",
                        "story_id": "story-001",
                    }
                ]
            }

            collector = ArticleCollector(extraction_settings)
            collector._detect_and_add_followups(sample_articles, context, date(2025, 1, 15))

        assert len(context.pending_followups) == 1
        assert context.pending_followups[0].event == "Test Event"
        assert context.pending_followups[0].story_id == "story-001"
