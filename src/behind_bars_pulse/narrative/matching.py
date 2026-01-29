# ABOUTME: Keyword-based story matching for linking articles to narratives.
# ABOUTME: Provides lightweight matching before AI extraction.

import re
from collections.abc import Sequence

from behind_bars_pulse.models import EnrichedArticle
from behind_bars_pulse.narrative.models import KeyCharacter, NarrativeContext, StoryThread


def normalize_text(text: str) -> str:
    """Normalize text for matching by lowercasing and removing extra whitespace."""
    return " ".join(text.lower().split())


def extract_keywords_from_text(text: str) -> set[str]:
    """Extract potential keywords from text (words 4+ chars)."""
    words = re.findall(r"\b[a-zA-ZàèéìòùÀÈÉÌÒÙ]{4,}\b", text.lower())
    return set(words)


def calculate_keyword_overlap(keywords1: Sequence[str], keywords2: Sequence[str]) -> float:
    """Calculate Jaccard similarity between two keyword sets.

    Returns:
        Overlap score between 0.0 and 1.0.
    """
    set1 = {k.lower() for k in keywords1}
    set2 = {k.lower() for k in keywords2}

    if not set1 or not set2:
        return 0.0

    intersection = len(set1 & set2)
    union = len(set1 | set2)

    return intersection / union if union > 0 else 0.0


def find_matching_stories(
    article: EnrichedArticle,
    context: NarrativeContext,
    min_score: float = 0.15,
) -> list[tuple[StoryThread, float]]:
    """Find stories that match an article based on keywords.

    Args:
        article: Article to match.
        context: Narrative context with stories.
        min_score: Minimum overlap score to consider a match.

    Returns:
        List of (story, score) tuples, sorted by score descending.
    """
    article_text = f"{article.title} {article.summary} {article.content[:500]}"
    article_keywords = extract_keywords_from_text(article_text)

    matches: list[tuple[StoryThread, float]] = []

    for story in context.ongoing_storylines:
        if story.status == "resolved":
            continue

        story_keywords = {kw.lower() for kw in story.keywords}
        story_keywords.add(story.topic.lower())
        story_keywords.update(extract_keywords_from_text(story.summary))

        score = calculate_keyword_overlap(list(article_keywords), list(story_keywords))

        if score >= min_score:
            matches.append((story, score))

    return sorted(matches, key=lambda x: x[1], reverse=True)


def find_mentioned_characters(
    article: EnrichedArticle,
    context: NarrativeContext,
) -> list[KeyCharacter]:
    """Find characters mentioned in an article.

    Args:
        article: Article to search.
        context: Narrative context with characters.

    Returns:
        List of mentioned characters.
    """
    article_text = normalize_text(f"{article.title} {article.content}")
    mentioned = []

    for character in context.key_characters:
        names_to_check = [character.name] + character.aliases

        for name in names_to_check:
            if normalize_text(name) in article_text:
                mentioned.append(character)
                break

    return mentioned


def suggest_keywords_for_story(
    articles: list[EnrichedArticle], existing_keywords: list[str]
) -> list[str]:
    """Suggest additional keywords for a story based on related articles.

    Args:
        articles: Articles related to the story.
        existing_keywords: Keywords already associated with the story.

    Returns:
        List of suggested new keywords.
    """
    existing_lower = {k.lower() for k in existing_keywords}
    keyword_counts: dict[str, int] = {}

    for article in articles:
        text = f"{article.title} {article.summary}"
        keywords = extract_keywords_from_text(text)

        for kw in keywords:
            if kw not in existing_lower:
                keyword_counts[kw] = keyword_counts.get(kw, 0) + 1

    sorted_keywords = sorted(keyword_counts.items(), key=lambda x: x[1], reverse=True)
    return [kw for kw, count in sorted_keywords[:10] if count >= 2]
