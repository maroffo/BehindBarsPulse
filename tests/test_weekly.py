# ABOUTME: Tests for weekly digest generator.
# ABOUTME: Validates weekly summary generation from daily bulletins.

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from behind_bars_pulse.config import Settings
from behind_bars_pulse.narrative.models import (
    FollowUp,
    KeyCharacter,
    NarrativeContext,
    StoryThread,
)
from behind_bars_pulse.newsletter.weekly import (
    WeeklyDigestContent,
    WeeklyDigestGenerator,
    _build_article_list,
    _resolve_article_refs,
)


@pytest.fixture
def weekly_settings(tmp_path) -> Settings:
    """Create settings for weekly testing."""
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
        templates_dir=tmp_path / "templates",
        data_dir=tmp_path / "data",
        weekly_lookback_days=7,
    )


@pytest.fixture
def sample_bulletins() -> list:
    """Create sample bulletin objects (SimpleNamespace mimicking ORM)."""
    return [
        SimpleNamespace(
            issue_date=date(2026, 2, 8),
            title="Titolo Sabato",
            subtitle="Sottotitolo sabato",
            content="Editoriale del sabato con analisi.",
            press_review=[
                {
                    "category": "Giustizia",
                    "comment": "Commento giustizia.",
                    "articles": [
                        {
                            "title": "Articolo Giustizia 1",
                            "link": "https://example.com/giustizia-1",
                            "author": "Mario Rossi",
                            "source": "Il Dubbio",
                            "published_date": "2026-02-08",
                        },
                    ],
                },
                {
                    "category": "Carceri",
                    "comment": "Commento carceri.",
                    "articles": [
                        {
                            "title": "Articolo Carceri 1",
                            "link": "https://example.com/carceri-1",
                            "author": "Anna Bianchi",
                            "source": "Avvenire",
                            "published_date": "2026-02-08",
                        },
                    ],
                },
            ],
        ),
        SimpleNamespace(
            issue_date=date(2026, 2, 7),
            title="Titolo Venerdì",
            subtitle="Sottotitolo venerdì",
            content="Editoriale del venerdì.",
            press_review=[
                {
                    "category": "Riforme",
                    "comment": "Commento riforme.",
                    "articles": [
                        {
                            "title": "Articolo Riforme 1",
                            "link": "https://example.com/riforme-1",
                            "author": "Luca Verdi",
                            "source": "La Repubblica",
                            "published_date": "2026-02-07",
                        },
                    ],
                },
            ],
        ),
        SimpleNamespace(
            issue_date=date(2026, 2, 6),
            title="Titolo Giovedì",
            subtitle=None,
            content="Editoriale giovedì.",
            press_review=None,
        ),
    ]


@pytest.fixture
def sample_narrative_context() -> NarrativeContext:
    """Create sample narrative context."""
    return NarrativeContext(
        ongoing_storylines=[
            StoryThread(
                id="story-001",
                topic="Decreto Carceri",
                status="active",
                first_seen=date(2025, 1, 1),
                last_update=date(2025, 1, 15),
                summary="Ongoing legislative reform.",
                keywords=["decreto", "carceri"],
                mention_count=5,
                impact_score=0.8,
            ),
        ],
        key_characters=[
            KeyCharacter(
                name="Carlo Nordio",
                role="Ministro della Giustizia",
            ),
        ],
        pending_followups=[
            FollowUp(
                id="fu-001",
                event="Voto Senato",
                expected_date=date(2025, 2, 1),
                created_at=date(2025, 1, 10),
            ),
        ],
    )


class TestWeeklyDigestContent:
    """Tests for WeeklyDigestContent."""

    def test_create_content(self) -> None:
        """WeeklyDigestContent can be created."""
        content = WeeklyDigestContent(
            weekly_title="Test Weekly Title",
            weekly_subtitle="Test Subtitle",
            narrative_arcs=[{"arc_title": "Test Arc", "summary": "Test summary"}],
            weekly_reflection="Test reflection text.",
            upcoming_events=[{"event": "Test Event", "date": "2025-02-01"}],
        )

        assert content.weekly_title == "Test Weekly Title"
        assert len(content.narrative_arcs) == 1
        assert len(content.upcoming_events) == 1


class TestWeeklyDigestGenerator:
    """Tests for WeeklyDigestGenerator."""

    def test_build_summaries_from_bulletins(
        self,
        weekly_settings: Settings,
        sample_bulletins: list,
    ) -> None:
        """_build_summaries_from_bulletins extracts and sorts by date."""
        generator = WeeklyDigestGenerator(weekly_settings)
        summaries = generator._build_summaries_from_bulletins(sample_bulletins)

        assert len(summaries) == 3
        # Sorted ascending by date
        assert summaries[0]["date"] == "2026-02-06"
        assert summaries[1]["date"] == "2026-02-07"
        assert summaries[2]["date"] == "2026-02-08"

    def test_build_summaries_maps_fields(
        self,
        weekly_settings: Settings,
        sample_bulletins: list,
    ) -> None:
        """_build_summaries_from_bulletins maps all bulletin fields correctly."""
        generator = WeeklyDigestGenerator(weekly_settings)
        summaries = generator._build_summaries_from_bulletins(sample_bulletins)

        saturday = summaries[2]  # Feb 8
        assert saturday["title"] == "Titolo Sabato"
        assert saturday["subtitle"] == "Sottotitolo sabato"
        assert saturday["editorial"] == "Editoriale del sabato con analisi."
        assert len(saturday["press_review"]) == 2
        assert saturday["press_review"][0]["category"] == "Giustizia"
        assert len(saturday["press_review"][0]["articles"]) == 1
        assert saturday["press_review"][0]["articles"][0]["title"] == "Articolo Giustizia 1"

    def test_build_summaries_handles_null_fields(
        self,
        weekly_settings: Settings,
        sample_bulletins: list,
    ) -> None:
        """_build_summaries_from_bulletins handles None subtitle and press_review."""
        generator = WeeklyDigestGenerator(weekly_settings)
        summaries = generator._build_summaries_from_bulletins(sample_bulletins)

        thursday = summaries[0]  # Feb 6
        assert thursday["subtitle"] == ""
        assert thursday["press_review"] == []

    def test_build_prompt_data(
        self,
        weekly_settings: Settings,
        sample_narrative_context: NarrativeContext,
    ) -> None:
        """_build_prompt_data formats data correctly."""
        generator = WeeklyDigestGenerator(weekly_settings)

        daily_summaries = [
            {
                "date": "2026-02-08",
                "title": "Test",
                "subtitle": "",
                "editorial": "Editorial text",
                "press_review": [{"category": "Cat", "comment": "Comment"}],
            }
        ]

        prompt_data = generator._build_prompt_data(
            daily_summaries,
            sample_narrative_context,
            date(2026, 2, 8),
        )

        assert "daily_summaries" in prompt_data
        assert len(prompt_data["daily_summaries"]) == 1
        assert prompt_data["daily_summaries"][0]["editorial"] == "Editorial text"
        assert "narrative_context" in prompt_data
        assert len(prompt_data["narrative_context"]["top_stories"]) == 1
        assert prompt_data["narrative_context"]["top_stories"][0]["topic"] == "Decreto Carceri"

    @patch("behind_bars_pulse.newsletter.weekly.NarrativeStorage")
    @patch("behind_bars_pulse.newsletter.weekly.AIService")
    def test_generate_creates_digest(
        self,
        mock_ai_class: MagicMock,
        mock_storage_class: MagicMock,
        weekly_settings: Settings,
        sample_bulletins: list,
        sample_narrative_context: NarrativeContext,
    ) -> None:
        """generate creates weekly digest content from bulletins."""
        # Setup mock AI (article_refs [0, 2] reference first and third articles)
        mock_ai = MagicMock()
        mock_ai._generate.return_value = """{
            "weekly_title": "Weekly Test Title",
            "weekly_subtitle": "Weekly Subtitle",
            "narrative_arcs": [
                {"arc_title": "Test Arc", "summary": "Arc summary", "article_refs": [0, 2]}
            ],
            "weekly_reflection": "Weekly reflection text.",
            "upcoming_events": []
        }"""
        mock_ai_class.return_value = mock_ai

        # Setup mock storage
        mock_storage = MagicMock()
        mock_storage.load_context.return_value = sample_narrative_context
        mock_storage_class.return_value = mock_storage

        generator = WeeklyDigestGenerator(weekly_settings)
        content = generator.generate(
            bulletins=sample_bulletins,
            reference_date=date(2026, 2, 8),
        )

        assert content.weekly_title == "Weekly Test Title"
        assert len(content.narrative_arcs) == 1
        # article_refs should be resolved to full article objects
        arc = content.narrative_arcs[0]
        assert "article_refs" not in arc
        assert len(arc["articles"]) == 2
        assert arc["articles"][0]["link"] == "https://example.com/riforme-1"
        assert arc["articles"][1]["link"] == "https://example.com/carceri-1"

    def test_generate_raises_when_no_bulletins(
        self,
        weekly_settings: Settings,
    ) -> None:
        """generate raises ValueError when no bulletins provided."""
        with patch("behind_bars_pulse.newsletter.weekly.NarrativeStorage"):
            generator = WeeklyDigestGenerator(weekly_settings)

            with pytest.raises(ValueError, match="No bulletins found"):
                generator.generate(bulletins=[], reference_date=date(2026, 2, 8))

    def test_build_context(
        self,
        weekly_settings: Settings,
    ) -> None:
        """build_context creates NewsletterContext for email."""
        generator = WeeklyDigestGenerator(weekly_settings)

        content = WeeklyDigestContent(
            weekly_title="Weekly Title",
            weekly_subtitle="Weekly Subtitle",
            narrative_arcs=[{"arc_title": "Test Arc", "summary": "Arc summary text here."}],
            weekly_reflection="Reflection on the week.",
            upcoming_events=[
                {"event": "Test Event", "date": "2025-02-01", "significance": "Important"}
            ],
        )

        context = generator.build_context(
            content,
            week_start=date(2025, 1, 9),
            week_end=date(2025, 1, 15),
        )

        assert "Digest Settimanale" in context.subject
        assert "09.01 - 15.01.2025" in context.subject
        assert context.newsletter_title == "Weekly Title"
        assert "Test Arc" in context.newsletter_opening
        assert "Reflection" in context.newsletter_closing
        assert "Test Event" in context.newsletter_closing

    def test_build_email_context(
        self,
        weekly_settings: Settings,
    ) -> None:
        """build_email_context creates dict for weekly digest template."""
        generator = WeeklyDigestGenerator(weekly_settings)

        content = WeeklyDigestContent(
            weekly_title="Weekly Title",
            weekly_subtitle="Weekly Subtitle",
            narrative_arcs=[{"arc_title": "Test Arc", "summary": "Arc summary."}],
            weekly_reflection="Reflection text.",
            upcoming_events=[{"event": "Test Event", "date": "2026-02-15"}],
        )

        ctx = generator.build_email_context(
            content,
            week_start=date(2026, 2, 3),
            week_end=date(2026, 2, 9),
        )

        assert isinstance(ctx, dict)
        assert ctx["subject"] == "BehindBars - Digest Settimanale - 03.02 - 09.02.2026"
        assert ctx["week_str"] == "03.02 - 09.02.2026"
        assert ctx["weekly_title"] == "Weekly Title"
        assert ctx["weekly_subtitle"] == "Weekly Subtitle"
        assert len(ctx["narrative_arcs"]) == 1
        assert ctx["narrative_arcs"][0]["arc_title"] == "Test Arc"
        assert ctx["weekly_reflection"] == "Reflection text."
        assert len(ctx["upcoming_events"]) == 1
        assert ctx["upcoming_events"][0]["event"] == "Test Event"

    def test_build_email_context_empty_subtitle(
        self,
        weekly_settings: Settings,
    ) -> None:
        """build_email_context handles empty subtitle."""
        generator = WeeklyDigestGenerator(weekly_settings)

        content = WeeklyDigestContent(
            weekly_title="Title Only",
            weekly_subtitle="",
            narrative_arcs=[],
            weekly_reflection="Reflection.",
            upcoming_events=[],
        )

        ctx = generator.build_email_context(
            content,
            week_start=date(2026, 1, 6),
            week_end=date(2026, 1, 12),
        )

        assert ctx["weekly_subtitle"] == ""
        assert ctx["narrative_arcs"] == []
        assert ctx["upcoming_events"] == []


class TestBuildArticleList:
    """Tests for _build_article_list helper."""

    def test_builds_flat_list_from_summaries(self) -> None:
        """_build_article_list collects articles with sequential indices."""
        summaries = [
            {
                "date": "2026-02-07",
                "press_review": [
                    {
                        "articles": [
                            {
                                "title": "Art A",
                                "link": "https://a.com",
                                "author": "A",
                                "source": "S1",
                            },
                            {
                                "title": "Art B",
                                "link": "https://b.com",
                                "author": "B",
                                "source": "S2",
                            },
                        ],
                    },
                ],
            },
            {
                "date": "2026-02-08",
                "press_review": [
                    {
                        "articles": [
                            {
                                "title": "Art C",
                                "link": "https://c.com",
                                "author": "C",
                                "source": "S3",
                            },
                        ],
                    },
                ],
            },
        ]
        result = _build_article_list(summaries)
        assert len(result) == 3
        assert result[0]["idx"] == 0
        assert result[0]["title"] == "Art A"
        assert result[2]["idx"] == 2
        assert result[2]["link"] == "https://c.com"

    def test_deduplicates_by_link(self) -> None:
        """_build_article_list skips duplicate URLs."""
        summaries = [
            {
                "date": "2026-02-07",
                "press_review": [
                    {"articles": [{"title": "Art A", "link": "https://a.com"}]},
                ],
            },
            {
                "date": "2026-02-08",
                "press_review": [
                    {"articles": [{"title": "Art A copy", "link": "https://a.com"}]},
                ],
            },
        ]
        result = _build_article_list(summaries)
        assert len(result) == 1

    def test_skips_empty_links(self) -> None:
        """_build_article_list skips articles without links."""
        summaries = [
            {
                "date": "2026-02-07",
                "press_review": [
                    {"articles": [{"title": "No link", "link": ""}]},
                ],
            },
        ]
        result = _build_article_list(summaries)
        assert len(result) == 0

    def test_handles_missing_articles_key(self) -> None:
        """_build_article_list handles categories without articles."""
        summaries = [
            {
                "date": "2026-02-07",
                "press_review": [
                    {"category": "Cat", "comment": "Comment"},
                ],
            },
        ]
        result = _build_article_list(summaries)
        assert len(result) == 0


class TestResolveArticleRefs:
    """Tests for _resolve_article_refs helper."""

    def test_resolves_valid_indices(self) -> None:
        """_resolve_article_refs maps indices to article objects."""
        all_articles = [
            {"idx": 0, "title": "Art A", "link": "https://a.com", "author": "A", "source": "S1"},
            {"idx": 1, "title": "Art B", "link": "https://b.com", "author": "B", "source": "S2"},
            {"idx": 2, "title": "Art C", "link": "https://c.com", "author": "C", "source": "S3"},
        ]
        arcs = [
            {"arc_title": "Arc 1", "summary": "Sum", "article_refs": [0, 2]},
        ]
        result = _resolve_article_refs(arcs, all_articles)
        assert len(result[0]["articles"]) == 2
        assert result[0]["articles"][0]["title"] == "Art A"
        assert result[0]["articles"][1]["link"] == "https://c.com"
        assert "article_refs" not in result[0]

    def test_skips_invalid_indices(self) -> None:
        """_resolve_article_refs skips out-of-range and non-parseable indices."""
        all_articles = [
            {"idx": 0, "title": "Art A", "link": "https://a.com"},
        ]
        arcs = [
            {"arc_title": "Arc", "summary": "Sum", "article_refs": [0, 5, -1, "bad", None]},
        ]
        result = _resolve_article_refs(arcs, all_articles)
        assert len(result[0]["articles"]) == 1

    def test_handles_stringified_indices(self) -> None:
        """_resolve_article_refs handles string indices from LLM output."""
        all_articles = [
            {"idx": 0, "title": "Art A", "link": "https://a.com", "author": "A", "source": "S1"},
            {"idx": 1, "title": "Art B", "link": "https://b.com", "author": "B", "source": "S2"},
        ]
        arcs = [
            {"arc_title": "Arc", "summary": "Sum", "article_refs": ["0", "1"]},
        ]
        result = _resolve_article_refs(arcs, all_articles)
        assert len(result[0]["articles"]) == 2
        assert result[0]["articles"][0]["title"] == "Art A"
        assert result[0]["articles"][1]["title"] == "Art B"

    def test_handles_missing_article_refs(self) -> None:
        """_resolve_article_refs handles arcs without article_refs."""
        arcs = [
            {"arc_title": "Arc", "summary": "Sum"},
        ]
        result = _resolve_article_refs(arcs, [])
        assert result[0]["articles"] == []

    def test_preserves_other_arc_fields(self) -> None:
        """_resolve_article_refs keeps arc_title, summary, outlook, etc."""
        arcs = [
            {
                "arc_title": "Arc",
                "summary": "Sum",
                "outlook": "Next week",
                "key_developments": ["Dev 1"],
                "article_refs": [],
            },
        ]
        result = _resolve_article_refs(arcs, [])
        assert result[0]["arc_title"] == "Arc"
        assert result[0]["outlook"] == "Next week"
        assert result[0]["key_developments"] == ["Dev 1"]
