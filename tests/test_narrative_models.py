# ABOUTME: Tests for narrative memory Pydantic models.
# ABOUTME: Validates StoryThread, KeyCharacter, FollowUp, and NarrativeContext.

from datetime import date

import pytest

from behind_bars_pulse.narrative.models import (
    CharacterPosition,
    FollowUp,
    KeyCharacter,
    NarrativeContext,
    StoryThread,
)


class TestStoryThread:
    """Tests for StoryThread model."""

    def test_create_minimal_story(self) -> None:
        """Story can be created with minimal fields."""
        story = StoryThread(
            id="story-001",
            topic="Decreto Carceri",
            first_seen=date(2025, 1, 1),
            last_update=date(2025, 1, 5),
            summary="Ongoing legislative reform.",
        )
        assert story.id == "story-001"
        assert story.topic == "Decreto Carceri"
        assert story.status == "active"
        assert story.mention_count == 1
        assert story.impact_score == 0.0
        assert story.weekly_highlight is False

    def test_create_full_story(self) -> None:
        """Story can be created with all fields."""
        story = StoryThread(
            id="story-002",
            topic="Suicidi in carcere",
            status="active",
            first_seen=date(2025, 1, 1),
            last_update=date(2025, 1, 10),
            summary="Ongoing crisis.",
            keywords=["suicidio", "sollicciano", "sovraffollamento"],
            related_articles=["https://example.com/article1"],
            mention_count=5,
            impact_score=0.8,
            weekly_highlight=True,
        )
        assert story.status == "active"
        assert len(story.keywords) == 3
        assert story.mention_count == 5
        assert story.impact_score == 0.8

    def test_impact_score_validation(self) -> None:
        """Impact score must be between 0 and 1."""
        with pytest.raises(ValueError):
            StoryThread(
                id="invalid",
                topic="Test",
                first_seen=date.today(),
                last_update=date.today(),
                summary="Test",
                impact_score=1.5,
            )


class TestKeyCharacter:
    """Tests for KeyCharacter model."""

    def test_create_character_minimal(self) -> None:
        """Character can be created with name and role."""
        char = KeyCharacter(name="Carlo Nordio", role="Ministro della Giustizia")
        assert char.name == "Carlo Nordio"
        assert char.role == "Ministro della Giustizia"
        assert char.aliases == []
        assert char.positions == []

    def test_create_character_with_positions(self) -> None:
        """Character can be created with positions history."""
        positions = [
            CharacterPosition(
                date=date(2025, 1, 5),
                stance="Il decreto carceri è sufficiente.",
                source_url="https://example.com/article",
            ),
            CharacterPosition(
                date=date(2025, 1, 10),
                stance="Servono nuove misure.",
            ),
        ]
        char = KeyCharacter(
            name="Carlo Nordio",
            role="Ministro della Giustizia",
            aliases=["Ministro Nordio", "il Ministro"],
            positions=positions,
        )
        assert len(char.aliases) == 2
        assert len(char.positions) == 2


class TestFollowUp:
    """Tests for FollowUp model."""

    def test_create_followup(self) -> None:
        """FollowUp can be created with required fields."""
        followup = FollowUp(
            id="followup-001",
            event="Voto Senato Decreto Carceri",
            expected_date=date(2025, 2, 1),
            created_at=date(2025, 1, 15),
        )
        assert followup.id == "followup-001"
        assert followup.event == "Voto Senato Decreto Carceri"
        assert followup.story_id is None
        assert followup.resolved is False

    def test_create_followup_linked_to_story(self) -> None:
        """FollowUp can be linked to a story."""
        followup = FollowUp(
            id="followup-002",
            event="Scadenza termini ricorso",
            expected_date=date(2025, 2, 15),
            story_id="story-001",
            created_at=date(2025, 1, 20),
        )
        assert followup.story_id == "story-001"


class TestNarrativeContext:
    """Tests for NarrativeContext model."""

    @pytest.fixture
    def sample_context(self) -> NarrativeContext:
        """Create a sample context for testing."""
        stories = [
            StoryThread(
                id="story-001",
                topic="Decreto Carceri",
                status="active",
                first_seen=date(2025, 1, 1),
                last_update=date(2025, 1, 10),
                summary="Legislative reform ongoing.",
                keywords=["decreto", "carceri", "riforma"],
            ),
            StoryThread(
                id="story-002",
                topic="Suicidi a Sollicciano",
                status="dormant",
                first_seen=date(2024, 12, 1),
                last_update=date(2024, 12, 20),
                summary="Tragic situation at Sollicciano.",
                keywords=["suicidio", "sollicciano"],
            ),
            StoryThread(
                id="story-003",
                topic="Caso chiuso",
                status="resolved",
                first_seen=date(2024, 11, 1),
                last_update=date(2024, 11, 30),
                summary="This case is resolved.",
                keywords=["vecchio", "caso"],
            ),
        ]

        characters = [
            KeyCharacter(
                name="Carlo Nordio",
                role="Ministro della Giustizia",
                aliases=["Ministro Nordio", "il Ministro"],
            ),
            KeyCharacter(
                name="Marco Pannella",
                role="Politico radicale",
                aliases=["Pannella"],
            ),
        ]

        followups = [
            FollowUp(
                id="f1",
                event="Voto Senato",
                expected_date=date(2025, 2, 1),
                created_at=date(2025, 1, 15),
                story_id="story-001",
            ),
            FollowUp(
                id="f2",
                event="Scadenza ricorso",
                expected_date=date(2025, 1, 20),
                created_at=date(2025, 1, 10),
                resolved=True,
            ),
        ]

        return NarrativeContext(
            ongoing_storylines=stories,
            key_characters=characters,
            pending_followups=followups,
        )

    def test_empty_context(self) -> None:
        """Empty context has sensible defaults."""
        ctx = NarrativeContext()
        assert ctx.ongoing_storylines == []
        assert ctx.key_characters == []
        assert ctx.pending_followups == []
        assert "Riflessivo" in ctx.editorial_tone

    def test_get_active_stories(self, sample_context: NarrativeContext) -> None:
        """get_active_stories returns only active stories."""
        active = sample_context.get_active_stories()
        assert len(active) == 1
        assert active[0].id == "story-001"

    def test_get_dormant_stories(self, sample_context: NarrativeContext) -> None:
        """get_dormant_stories returns only dormant stories."""
        dormant = sample_context.get_dormant_stories()
        assert len(dormant) == 1
        assert dormant[0].id == "story-002"

    def test_get_pending_followups(self, sample_context: NarrativeContext) -> None:
        """get_pending_followups excludes resolved followups."""
        pending = sample_context.get_pending_followups()
        assert len(pending) == 1
        assert pending[0].id == "f1"

    def test_get_due_followups(self, sample_context: NarrativeContext) -> None:
        """get_due_followups returns followups due by given date."""
        due = sample_context.get_due_followups(date(2025, 2, 1))
        assert len(due) == 1
        assert due[0].id == "f1"

        due_early = sample_context.get_due_followups(date(2025, 1, 15))
        assert len(due_early) == 0

    def test_get_character_by_name(self, sample_context: NarrativeContext) -> None:
        """get_character_by_name finds by name or alias."""
        char = sample_context.get_character_by_name("Carlo Nordio")
        assert char is not None
        assert char.name == "Carlo Nordio"

        char_alias = sample_context.get_character_by_name("Ministro Nordio")
        assert char_alias is not None
        assert char_alias.name == "Carlo Nordio"

        char_not_found = sample_context.get_character_by_name("Unknown Person")
        assert char_not_found is None

    def test_get_character_by_name_case_insensitive(self, sample_context: NarrativeContext) -> None:
        """Character search is case insensitive."""
        char = sample_context.get_character_by_name("carlo nordio")
        assert char is not None
        assert char.name == "Carlo Nordio"

    def test_get_story_by_id(self, sample_context: NarrativeContext) -> None:
        """get_story_by_id finds story by ID."""
        story = sample_context.get_story_by_id("story-001")
        assert story is not None
        assert story.topic == "Decreto Carceri"

        not_found = sample_context.get_story_by_id("nonexistent")
        assert not_found is None

    def test_get_stories_by_keyword(self, sample_context: NarrativeContext) -> None:
        """get_stories_by_keyword finds stories matching keyword."""
        matches = sample_context.get_stories_by_keyword("decreto")
        assert len(matches) == 1
        assert matches[0].id == "story-001"

        matches_topic = sample_context.get_stories_by_keyword("Sollicciano")
        assert len(matches_topic) == 1
        assert matches_topic[0].id == "story-002"

    def test_serialization_round_trip(self, sample_context: NarrativeContext) -> None:
        """Context can be serialized to JSON and back."""
        json_str = sample_context.model_dump_json()
        restored = NarrativeContext.model_validate_json(json_str)

        assert len(restored.ongoing_storylines) == 3
        assert len(restored.key_characters) == 2
        assert len(restored.pending_followups) == 2
