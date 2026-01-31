# ABOUTME: Pydantic models for narrative memory system.
# ABOUTME: Tracks ongoing stories, key characters, and follow-up events.

from datetime import date, datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class StoryStatus(str, Enum):
    """Status of an ongoing story thread."""

    ACTIVE = "active"
    DORMANT = "dormant"
    RESOLVED = "resolved"


class StoryThread(BaseModel):
    """An ongoing story or narrative thread being tracked across newsletters."""

    id: str = Field(description="Unique identifier (UUID)")
    topic: str = Field(description="Main topic, e.g. 'Decreto Carceri'")
    status: Literal["active", "dormant", "resolved"] = "active"
    first_seen: date
    last_update: date
    summary: str = Field(description="Current summary of the story")
    keywords: list[str] = Field(default_factory=list, description="Keywords for matching")
    related_articles: list[str] = Field(default_factory=list)
    mention_count: int = Field(default=1, description="Times mentioned in newsletters")
    impact_score: float = Field(default=0.0, ge=0.0, le=1.0, description="AI-calculated impact")
    weekly_highlight: bool = Field(default=False, description="Flag for weekly inclusion")


class CharacterPosition(BaseModel):
    """A recorded position or stance by a key character on a specific date."""

    date: date
    stance: str = Field(description="Position or statement")
    source_url: str | None = None


class KeyCharacter(BaseModel):
    """A key figure in the Italian prison/justice system being tracked."""

    name: str = Field(description="Full name, e.g. 'Carlo Nordio'")
    role: str = Field(description="Current role, e.g. 'Ministro della Giustizia'")
    aliases: list[str] = Field(default_factory=list, description="Alternative names")
    positions: list[CharacterPosition] = Field(default_factory=list)


class FollowUp(BaseModel):
    """An upcoming event or deadline to track and reference."""

    id: str = Field(description="Unique identifier (UUID)")
    event: str = Field(description="Description, e.g. 'Voto Senato Decreto Carceri'")
    expected_date: date
    story_id: str | None = Field(default=None, description="Related story thread ID")
    created_at: date
    resolved: bool = False


class NarrativeContext(BaseModel):
    """Complete narrative context for newsletter generation."""

    ongoing_storylines: list[StoryThread] = Field(default_factory=list)
    key_characters: list[KeyCharacter] = Field(default_factory=list)
    editorial_tone: str = Field(
        default="Riflessivo e professionale, attento ai progressi ma consapevole delle sfide sistemiche",
        description="Consistent editorial tone guidance",
    )
    pending_followups: list[FollowUp] = Field(default_factory=list)
    last_updated: datetime = Field(default_factory=datetime.now)

    def get_active_stories(self) -> list[StoryThread]:
        """Return stories that are still active."""
        return [s for s in self.ongoing_storylines if s.status == "active"]

    def get_dormant_stories(self) -> list[StoryThread]:
        """Return stories that are dormant but not resolved."""
        return [s for s in self.ongoing_storylines if s.status == "dormant"]

    def get_pending_followups(self) -> list[FollowUp]:
        """Return follow-ups that are not yet resolved."""
        return [f for f in self.pending_followups if not f.resolved]

    def get_due_followups(self, as_of: date) -> list[FollowUp]:
        """Return follow-ups that are due on or before the given date."""
        return [f for f in self.pending_followups if not f.resolved and f.expected_date <= as_of]

    def get_character_by_name(self, name: str) -> KeyCharacter | None:
        """Find a character by name or alias."""
        name_lower = name.lower()
        for char in self.key_characters:
            if char.name.lower() == name_lower:
                return char
            if any(alias.lower() == name_lower for alias in char.aliases):
                return char
        return None

    def get_story_by_id(self, story_id: str) -> StoryThread | None:
        """Find a story by its ID."""
        for story in self.ongoing_storylines:
            if story.id == story_id:
                return story
        return None

    def get_stories_by_keyword(self, keyword: str) -> list[StoryThread]:
        """Find stories matching a keyword."""
        keyword_lower = keyword.lower()
        return [
            s
            for s in self.ongoing_storylines
            if keyword_lower in s.topic.lower()
            or any(keyword_lower in kw.lower() for kw in s.keywords)
        ]
