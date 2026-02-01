# ABOUTME: Tests for CLI argument parsing and command dispatch.
# ABOUTME: Validates argparse configuration and subcommand routing.

import argparse
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from behind_bars_pulse.__main__ import cmd_status, create_parser, main
from behind_bars_pulse.config import Settings


@pytest.fixture
def cli_settings(tmp_path: Path) -> Settings:
    """Create settings for CLI testing."""
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


class TestCreateParser:
    """Tests for argument parser creation."""

    def test_parser_creation(self) -> None:
        """Parser is created successfully."""
        parser = create_parser()
        assert isinstance(parser, argparse.ArgumentParser)

    def test_collect_command(self) -> None:
        """Collect command parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["collect"])
        assert args.command == "collect"
        assert args.date is None

    def test_collect_with_date(self) -> None:
        """Collect command accepts date argument."""
        parser = create_parser()
        args = parser.parse_args(["collect", "--date", "2025-01-15"])
        assert args.command == "collect"
        assert args.date == "2025-01-15"

    def test_generate_command(self) -> None:
        """Generate command parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["generate"])
        assert args.command == "generate"
        assert args.days_back == 7  # Default value

    def test_generate_with_days_back(self) -> None:
        """Generate command accepts days-back argument."""
        parser = create_parser()
        args = parser.parse_args(["generate", "--days-back", "14"])
        assert args.command == "generate"
        assert args.days_back == 14

    def test_weekly_command(self) -> None:
        """Weekly command parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["weekly"])
        assert args.command == "weekly"

    def test_status_command(self) -> None:
        """Status command parses correctly."""
        parser = create_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_no_command(self) -> None:
        """No command results in None."""
        parser = create_parser()
        args = parser.parse_args([])
        assert args.command is None


class TestCmdStatus:
    """Tests for status command."""

    @patch("behind_bars_pulse.narrative.storage.NarrativeStorage")
    def test_status_displays_context(
        self, mock_storage_class: MagicMock, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Status command displays narrative context info."""
        from behind_bars_pulse.narrative.models import (
            FollowUp,
            KeyCharacter,
            NarrativeContext,
            StoryThread,
        )

        mock_context = NarrativeContext(
            ongoing_storylines=[
                StoryThread(
                    id="s1",
                    topic="Test Story",
                    status="active",
                    first_seen=date(2025, 1, 1),
                    last_update=date(2025, 1, 10),
                    summary="Test",
                    mention_count=3,
                    impact_score=0.7,
                ),
            ],
            key_characters=[
                KeyCharacter(name="Test Person", role="Test Role"),
            ],
            pending_followups=[
                FollowUp(
                    id="f1",
                    event="Test Event",
                    expected_date=date(2025, 2, 1),
                    created_at=date(2025, 1, 15),
                ),
            ],
        )

        mock_storage = MagicMock()
        mock_storage.load_context.return_value = mock_context
        mock_storage.get_available_collection_dates.return_value = []
        mock_storage_class.return_value = mock_storage

        args = argparse.Namespace()
        result = cmd_status(args)

        assert result == 0
        captured = capsys.readouterr()
        assert "Test Story" in captured.out
        assert "Test Person" in captured.out
        assert "Test Event" in captured.out


class TestMain:
    """Tests for main entry point."""

    @patch("behind_bars_pulse.__main__.cmd_generate")
    @patch("behind_bars_pulse.__main__.configure_logging")
    def test_main_default_runs_generate(
        self, _mock_logging: MagicMock, mock_generate: MagicMock
    ) -> None:
        """Main with no args runs generate command."""
        mock_generate.return_value = 0

        with patch("sys.argv", ["behind_bars_pulse"]):
            result = main()

        mock_generate.assert_called_once()
        assert result == 0

    @patch("behind_bars_pulse.__main__.cmd_collect")
    @patch("behind_bars_pulse.__main__.configure_logging")
    def test_main_collect_command(self, _mock_logging: MagicMock, mock_collect: MagicMock) -> None:
        """Main routes collect command correctly."""
        mock_collect.return_value = 0

        with patch("sys.argv", ["behind_bars_pulse", "collect"]):
            result = main()

        mock_collect.assert_called_once()
        assert result == 0

    @patch("behind_bars_pulse.__main__.cmd_status")
    @patch("behind_bars_pulse.__main__.configure_logging")
    def test_main_status_command(self, _mock_logging: MagicMock, mock_status: MagicMock) -> None:
        """Main routes status command correctly."""
        mock_status.return_value = 0

        with patch("sys.argv", ["behind_bars_pulse", "status"]):
            result = main()

        mock_status.assert_called_once()
        assert result == 0
