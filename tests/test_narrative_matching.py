# ABOUTME: Tests for story matching functions.
# ABOUTME: Validates keyword extraction and story-article matching.

from datetime import date

import pytest

from behind_bars_pulse.models import EnrichedArticle
from behind_bars_pulse.narrative.matching import (
    calculate_keyword_overlap,
    extract_keywords_from_text,
    find_matching_stories,
    find_mentioned_characters,
    normalize_text,
    suggest_keywords_for_story,
)
from behind_bars_pulse.narrative.models import KeyCharacter, NarrativeContext, StoryThread


class TestNormalizeText:
    """Tests for normalize_text function."""

    def test_lowercase_and_strip(self) -> None:
        """Text is lowercased and whitespace normalized."""
        assert normalize_text("  Hello   World  ") == "hello world"
        assert normalize_text("UPPERCASE") == "uppercase"

    def test_preserves_accented_chars(self) -> None:
        """Italian accented characters are preserved."""
        assert normalize_text("Perché così") == "perché così"


class TestExtractKeywords:
    """Tests for extract_keywords_from_text."""

    def test_extracts_words(self) -> None:
        """Extracts words 4+ characters."""
        text = "Il decreto carceri è in discussione"
        keywords = extract_keywords_from_text(text)

        assert "decreto" in keywords
        assert "carceri" in keywords
        assert "discussione" in keywords
        assert "il" not in keywords  # Too short
        assert "è" not in keywords  # Too short

    def test_handles_accents(self) -> None:
        """Handles Italian accented characters."""
        text = "Il perché della questione è importante"
        keywords = extract_keywords_from_text(text)

        assert "perché" in keywords
        assert "questione" in keywords
        assert "importante" in keywords


class TestKeywordOverlap:
    """Tests for calculate_keyword_overlap."""

    def test_identical_sets(self) -> None:
        """Identical sets have overlap of 1.0."""
        assert calculate_keyword_overlap(["a", "b", "c"], ["a", "b", "c"]) == 1.0

    def test_no_overlap(self) -> None:
        """Disjoint sets have overlap of 0.0."""
        assert calculate_keyword_overlap(["a", "b"], ["c", "d"]) == 0.0

    def test_partial_overlap(self) -> None:
        """Partial overlap is calculated correctly."""
        # Jaccard: intersection=2, union=4, so 0.5
        overlap = calculate_keyword_overlap(["a", "b", "c"], ["b", "c", "d"])
        assert overlap == pytest.approx(0.5)

    def test_empty_sets(self) -> None:
        """Empty sets return 0.0."""
        assert calculate_keyword_overlap([], ["a"]) == 0.0
        assert calculate_keyword_overlap(["a"], []) == 0.0
        assert calculate_keyword_overlap([], []) == 0.0

    def test_case_insensitive(self) -> None:
        """Comparison is case insensitive."""
        assert calculate_keyword_overlap(["ABC"], ["abc"]) == 1.0


class TestFindMatchingStories:
    """Tests for find_matching_stories."""

    @pytest.fixture
    def sample_context(self) -> NarrativeContext:
        """Create context with test stories."""
        return NarrativeContext(
            ongoing_storylines=[
                StoryThread(
                    id="decreto",
                    topic="Decreto Carceri",
                    first_seen=date(2025, 1, 1),
                    last_update=date(2025, 1, 10),
                    summary="Riforma legislativa sul sistema carcerario.",
                    keywords=["decreto", "carceri", "riforma", "legislativa"],
                ),
                StoryThread(
                    id="suicidi",
                    topic="Suicidi in carcere",
                    first_seen=date(2025, 1, 1),
                    last_update=date(2025, 1, 10),
                    summary="Emergenza suicidi nel sistema penitenziario.",
                    keywords=["suicidio", "carcere", "emergenza", "penitenziario"],
                ),
                StoryThread(
                    id="resolved",
                    topic="Caso Risolto",
                    status="resolved",
                    first_seen=date(2024, 1, 1),
                    last_update=date(2024, 12, 1),
                    summary="This case is closed.",
                    keywords=["caso", "risolto"],
                ),
            ],
        )

    def test_matches_by_keyword(self, sample_context: NarrativeContext) -> None:
        """Articles match stories by keyword overlap."""
        article = EnrichedArticle(
            title="Nuovo decreto carceri in parlamento",
            link="https://example.com/article",
            content="La riforma legislativa prosegue.",
            author="Test",
            source="Test",
            summary="Il decreto carceri avanza nella discussione parlamentare.",
        )

        matches = find_matching_stories(article, sample_context, min_score=0.1)

        assert len(matches) >= 1
        story_ids = [s.id for s, _ in matches]
        assert "decreto" in story_ids

    def test_excludes_resolved_stories(self, sample_context: NarrativeContext) -> None:
        """Resolved stories are not matched."""
        article = EnrichedArticle(
            title="Caso risolto finalmente",
            link="https://example.com/article",
            content="Il caso è stato risolto.",
            author="Test",
            source="Test",
            summary="Caso risolto.",
        )

        matches = find_matching_stories(article, sample_context)

        story_ids = [s.id for s, _ in matches]
        assert "resolved" not in story_ids

    def test_respects_min_score(self, sample_context: NarrativeContext) -> None:
        """Only matches above min_score are returned."""
        article = EnrichedArticle(
            title="Unrelated article",
            link="https://example.com/article",
            content="Completely unrelated content about sports.",
            author="Test",
            source="Test",
            summary="Sports news.",
        )

        matches = find_matching_stories(article, sample_context, min_score=0.5)

        assert len(matches) == 0


class TestFindMentionedCharacters:
    """Tests for find_mentioned_characters."""

    @pytest.fixture
    def sample_context(self) -> NarrativeContext:
        """Create context with test characters."""
        return NarrativeContext(
            key_characters=[
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
            ],
        )

    def test_finds_by_full_name(self, sample_context: NarrativeContext) -> None:
        """Finds characters by full name."""
        article = EnrichedArticle(
            title="Dichiarazioni di Carlo Nordio",
            link="https://example.com/article",
            content="Carlo Nordio ha dichiarato...",
            author="Test",
            source="Test",
            summary="Test",
        )

        mentioned = find_mentioned_characters(article, sample_context)

        assert len(mentioned) == 1
        assert mentioned[0].name == "Carlo Nordio"

    def test_finds_by_alias(self, sample_context: NarrativeContext) -> None:
        """Finds characters by alias."""
        article = EnrichedArticle(
            title="Il Ministro Nordio interviene",
            link="https://example.com/article",
            content="Ministro Nordio ha parlato.",
            author="Test",
            source="Test",
            summary="Test",
        )

        mentioned = find_mentioned_characters(article, sample_context)

        assert len(mentioned) == 1
        assert mentioned[0].name == "Carlo Nordio"

    def test_finds_multiple_characters(self, sample_context: NarrativeContext) -> None:
        """Finds multiple mentioned characters."""
        article = EnrichedArticle(
            title="Nordio e Pannella a confronto",
            link="https://example.com/article",
            content="Carlo Nordio e Marco Pannella discutono.",
            author="Test",
            source="Test",
            summary="Test",
        )

        mentioned = find_mentioned_characters(article, sample_context)

        assert len(mentioned) == 2
        names = {c.name for c in mentioned}
        assert names == {"Carlo Nordio", "Marco Pannella"}

    def test_case_insensitive(self, sample_context: NarrativeContext) -> None:
        """Search is case insensitive."""
        article = EnrichedArticle(
            title="CARLO NORDIO ANNUNCIA",
            link="https://example.com/article",
            content="carlo nordio ha detto",
            author="Test",
            source="Test",
            summary="Test",
        )

        mentioned = find_mentioned_characters(article, sample_context)

        assert len(mentioned) == 1


class TestSuggestKeywords:
    """Tests for suggest_keywords_for_story."""

    def test_suggests_common_keywords(self) -> None:
        """Suggests keywords appearing in multiple articles."""
        articles = [
            EnrichedArticle(
                title="Sovraffollamento a Sollicciano",
                link="https://example.com/1",
                content="Test",
                summary="Il sovraffollamento peggiora a Sollicciano.",
            ),
            EnrichedArticle(
                title="Emergenza sovraffollamento Sollicciano",
                link="https://example.com/2",
                content="Test",
                summary="Emergenza sovraffollamento nelle carceri toscane a Sollicciano.",
            ),
        ]

        existing = ["carceri", "italia"]
        suggestions = suggest_keywords_for_story(articles, existing)

        assert "sovraffollamento" in suggestions
        assert "sollicciano" in suggestions  # Now appears in both articles
        assert "carceri" not in suggestions  # Already exists

    def test_excludes_existing_keywords(self) -> None:
        """Doesn't suggest keywords that already exist."""
        articles = [
            EnrichedArticle(
                title="Decreto carceri",
                link="https://example.com/1",
                content="Test",
                summary="Decreto discusso.",
            ),
        ]

        existing = ["decreto", "carceri"]
        suggestions = suggest_keywords_for_story(articles, existing)

        assert "decreto" not in suggestions
        assert "carceri" not in suggestions
