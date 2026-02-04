# ABOUTME: Tests for bulletin generation and models.
# ABOUTME: Verifies BulletinGenerator, Pydantic models, and editorial comment extraction.

from datetime import date

import pytest

from behind_bars_pulse.bulletin.models import Bulletin, BulletinContent, EditorialCommentChunk
from behind_bars_pulse.config import Settings


class TestBulletinModels:
    """Tests for bulletin Pydantic models."""

    def test_bulletin_content_creation(self) -> None:
        """BulletinContent should be created with all fields."""
        content = BulletinContent(
            title="Test Title",
            subtitle="Test Subtitle",
            content="Test content text",
            key_topics=["topic1", "topic2"],
            sources_cited=["Il Dubbio", "Avvenire"],
        )

        assert content.title == "Test Title"
        assert content.subtitle == "Test Subtitle"
        assert content.content == "Test content text"
        assert len(content.key_topics) == 2
        assert "Il Dubbio" in content.sources_cited

    def test_bulletin_creation(self) -> None:
        """Bulletin should be created with defaults."""
        bulletin = Bulletin(
            issue_date=date(2026, 2, 3),
            title="Test Bulletin",
            subtitle="Subtitle",
            content="Content",
        )

        assert bulletin.issue_date == date(2026, 2, 3)
        assert bulletin.title == "Test Bulletin"
        assert bulletin.key_topics == []
        assert bulletin.sources_cited == []
        assert bulletin.articles_count == 0

    def test_bulletin_with_metadata(self) -> None:
        """Bulletin should accept all metadata fields."""
        bulletin = Bulletin(
            issue_date=date(2026, 2, 3),
            title="Test Bulletin",
            subtitle="Subtitle",
            content="Content",
            key_topics=["sovraffollamento", "suicidi"],
            sources_cited=["Il Dubbio"],
            articles_count=15,
        )

        assert bulletin.articles_count == 15
        assert len(bulletin.key_topics) == 2

    def test_editorial_comment_chunk_creation(self) -> None:
        """EditorialCommentChunk should be created correctly."""
        chunk = EditorialCommentChunk(
            source_type="bulletin",
            source_id=1,
            source_date=date(2026, 2, 3),
            category="paragraph_1",
            content="Test content for semantic search",
        )

        assert chunk.source_type == "bulletin"
        assert chunk.source_id == 1
        assert chunk.category == "paragraph_1"


class TestBulletinGenerator:
    """Tests for BulletinGenerator class."""

    def test_generator_initialization(self, mock_settings: Settings) -> None:
        """BulletinGenerator should initialize with settings."""
        from behind_bars_pulse.bulletin.generator import BulletinGenerator

        generator = BulletinGenerator(mock_settings)
        assert generator.settings == mock_settings

    def test_extract_editorial_comments_single_paragraph(self, mock_settings: Settings) -> None:
        """Should extract single chunk for short content."""
        from behind_bars_pulse.bulletin.generator import BulletinGenerator

        generator = BulletinGenerator(mock_settings)

        bulletin = Bulletin(
            issue_date=date(2026, 2, 3),
            title="Test",
            subtitle="Test",
            content="Short content without paragraph breaks.",
        )

        chunks = generator.extract_editorial_comments(bulletin, bulletin_id=1)

        assert len(chunks) == 1
        assert chunks[0].source_type == "bulletin"
        assert chunks[0].source_id == 1
        assert chunks[0].content == "Short content without paragraph breaks."

    def test_extract_editorial_comments_multiple_paragraphs(self, mock_settings: Settings) -> None:
        """Should extract multiple chunks for long content with paragraphs."""
        from behind_bars_pulse.bulletin.generator import BulletinGenerator

        generator = BulletinGenerator(mock_settings)

        long_content = """Primo paragrafo con contenuto sostanziale che supera i cento caratteri per essere incluso come chunk separato per la ricerca semantica.

Secondo paragrafo anche questo abbastanza lungo per essere considerato un chunk separato con informazioni rilevanti sulla situazione carceraria italiana.

Terzo paragrafo finale che conclude l'analisi del bollettino con riflessioni aggiuntive sulla situazione attuale delle carceri italiane."""

        bulletin = Bulletin(
            issue_date=date(2026, 2, 3),
            title="Test",
            subtitle="Test",
            content=long_content,
        )

        chunks = generator.extract_editorial_comments(bulletin, bulletin_id=1)

        assert len(chunks) == 3
        assert all(c.source_type == "bulletin" for c in chunks)
        assert chunks[0].category == "paragraph_1"
        assert chunks[1].category == "paragraph_2"
        assert chunks[2].category == "paragraph_3"


class TestBulletinContent:
    """Tests for BulletinContent JSON serialization."""

    def test_bulletin_content_json_serialization(self) -> None:
        """BulletinContent should serialize to JSON."""
        content = BulletinContent(
            title="Test Title",
            subtitle="Test Subtitle",
            content="Test content",
            key_topics=["topic1"],
            sources_cited=["source1"],
        )

        json_str = content.model_dump_json()
        assert "Test Title" in json_str
        assert "topic1" in json_str

    def test_bulletin_json_serialization(self) -> None:
        """Bulletin should serialize to JSON with date."""
        bulletin = Bulletin(
            issue_date=date(2026, 2, 3),
            title="Test",
            subtitle="Test",
            content="Content",
        )

        json_data = bulletin.model_dump(mode="json")
        assert json_data["issue_date"] == "2026-02-03"
