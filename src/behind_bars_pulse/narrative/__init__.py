# ABOUTME: Narrative memory module for tracking ongoing stories and context.
# ABOUTME: Exports models and storage classes for narrative continuity.

from behind_bars_pulse.narrative.matching import (
    find_matching_stories,
    find_mentioned_characters,
    suggest_keywords_for_story,
)
from behind_bars_pulse.narrative.models import (
    CharacterPosition,
    FollowUp,
    KeyCharacter,
    NarrativeContext,
    StoryThread,
)
from behind_bars_pulse.narrative.storage import NarrativeStorage

__all__ = [
    "CharacterPosition",
    "FollowUp",
    "KeyCharacter",
    "NarrativeContext",
    "NarrativeStorage",
    "StoryThread",
    "find_matching_stories",
    "find_mentioned_characters",
    "suggest_keywords_for_story",
]
