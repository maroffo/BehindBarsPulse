# ABOUTME: Tests for email sender with dict context and template overrides.
# ABOUTME: Validates send/save_preview work with both NewsletterContext and plain dict.

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from behind_bars_pulse.config import Settings
from behind_bars_pulse.email.sender import EmailSender
from behind_bars_pulse.models import NewsletterContext


@pytest.fixture
def sender_settings(tmp_path: Path) -> Settings:
    """Create settings for sender testing with real template dir."""
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
    )


@pytest.fixture
def sender(sender_settings: Settings) -> EmailSender:
    """Create EmailSender with test settings."""
    return EmailSender(sender_settings)


@pytest.fixture
def sample_newsletter_context() -> NewsletterContext:
    """Create a minimal NewsletterContext for testing."""
    return NewsletterContext(
        subject="Test Daily Subject",
        today_str="10.02.2026",
        newsletter_title="Daily Title",
        newsletter_subtitle="Daily Subtitle",
        newsletter_opening="Opening text here.",
        newsletter_closing="Closing text here.",
        press_review=[],
        notification_address_list=["test@example.com"],
    )


@pytest.fixture
def sample_weekly_dict() -> dict:
    """Create a weekly digest email context dict."""
    return {
        "subject": "BehindBars - Digest Settimanale - 03.02 - 09.02.2026",
        "week_str": "03.02 - 09.02.2026",
        "weekly_title": "Weekly Title",
        "weekly_subtitle": "Weekly Subtitle",
        "narrative_arcs": [
            {"arc_title": "Arc One", "summary": "Summary of arc one."},
            {"arc_title": "Arc Two", "summary": "Summary of arc two."},
        ],
        "weekly_reflection": "Reflection on the week.",
        "upcoming_events": [
            {"event": "Voto Senato", "date": "2026-02-15"},
        ],
    }


class TestSendWithNewsletterContext:
    """Tests for send() with Pydantic NewsletterContext (backwards compatibility)."""

    @patch.object(EmailSender, "_send_smtp")
    def test_send_with_newsletter_context(
        self,
        mock_smtp: MagicMock,
        sender: EmailSender,
        sample_newsletter_context: NewsletterContext,
    ) -> None:
        """send() works with NewsletterContext and uses daily templates by default."""
        sender.send(sample_newsletter_context)

        mock_smtp.assert_called_once()
        message = mock_smtp.call_args[0][0]
        assert message["Subject"] == "Test Daily Subject"

    @patch.object(EmailSender, "_send_smtp")
    def test_send_uses_context_recipients(
        self,
        mock_smtp: MagicMock,
        sender: EmailSender,
        sample_newsletter_context: NewsletterContext,
    ) -> None:
        """send() uses notification_address_list from NewsletterContext."""
        sender.send(sample_newsletter_context)

        recipients = mock_smtp.call_args[0][1]
        assert recipients == ["test@example.com"]

    @patch.object(EmailSender, "_send_smtp")
    def test_send_falls_back_to_default_recipient(
        self,
        mock_smtp: MagicMock,
        sender: EmailSender,
    ) -> None:
        """send() falls back to default_recipient when context has no recipients."""
        context = NewsletterContext(
            subject="Test",
            today_str="10.02.2026",
            newsletter_title="Title",
            newsletter_subtitle="Sub",
            newsletter_opening="Open",
            newsletter_closing="Close",
            press_review=[],
            notification_address_list=[],
        )
        sender.send(context)

        recipients = mock_smtp.call_args[0][1]
        assert recipients == ["recipient@example.com"]


class TestSendWithDict:
    """Tests for send() with plain dict context."""

    @patch.object(EmailSender, "_send_smtp")
    def test_send_with_dict_context(
        self,
        mock_smtp: MagicMock,
        sender: EmailSender,
        sample_weekly_dict: dict,
    ) -> None:
        """send() works with dict context and weekly templates."""
        sender.send(
            sample_weekly_dict,
            recipients=["weekly@example.com"],
            html_template="weekly_digest_template.html",
            txt_template="weekly_digest_template.txt",
        )

        mock_smtp.assert_called_once()
        message = mock_smtp.call_args[0][0]
        assert message["Subject"] == "BehindBars - Digest Settimanale - 03.02 - 09.02.2026"
        recipients = mock_smtp.call_args[0][1]
        assert recipients == ["weekly@example.com"]

    @patch.object(EmailSender, "_send_smtp")
    def test_send_dict_uses_default_recipient(
        self,
        mock_smtp: MagicMock,
        sender: EmailSender,
        sample_weekly_dict: dict,
    ) -> None:
        """send() with dict falls back to default_recipient when no recipients given."""
        sender.send(
            sample_weekly_dict,
            html_template="weekly_digest_template.html",
            txt_template="weekly_digest_template.txt",
        )

        recipients = mock_smtp.call_args[0][1]
        assert recipients == ["recipient@example.com"]

    @patch.object(EmailSender, "_send_smtp")
    def test_send_dict_default_subject(
        self,
        mock_smtp: MagicMock,
        sender: EmailSender,
    ) -> None:
        """send() with dict uses 'BehindBars' as fallback subject."""
        sender.send(
            {
                "week_str": "test",
                "weekly_title": "t",
                "weekly_subtitle": "",
                "narrative_arcs": [],
                "weekly_reflection": "",
                "upcoming_events": [],
            },
            recipients=["x@example.com"],
            html_template="weekly_digest_template.html",
            txt_template="weekly_digest_template.txt",
        )

        message = mock_smtp.call_args[0][0]
        assert message["Subject"] == "BehindBars"


class TestSavePreview:
    """Tests for save_preview() with both context types."""

    def test_save_preview_with_newsletter_context(
        self,
        sender: EmailSender,
        sample_newsletter_context: NewsletterContext,
    ) -> None:
        """save_preview() with NewsletterContext returns HTML file path."""
        path = sender.save_preview(sample_newsletter_context, issue_date=date(2026, 2, 10))

        assert path.exists()
        assert path.suffix == ".html"
        assert "20260210" in path.name
        assert "_preview" in path.name

    def test_save_preview_with_dict_context(
        self,
        sender: EmailSender,
        sample_weekly_dict: dict,
    ) -> None:
        """save_preview() with dict and weekly templates renders correctly."""
        path = sender.save_preview(
            sample_weekly_dict,
            issue_date=date(2026, 2, 9),
            html_template="weekly_digest_template.html",
            txt_template="weekly_digest_template.txt",
        )

        assert path.exists()
        html_content = path.read_text()
        assert "Digest Settimanale" in html_content
        assert "Weekly Title" in html_content
        assert "Arc One" in html_content
        assert "Voto Senato" in html_content

    def test_save_preview_dict_creates_txt_too(
        self,
        sender: EmailSender,
        sample_weekly_dict: dict,
    ) -> None:
        """save_preview() with dict also creates the txt preview."""
        path = sender.save_preview(
            sample_weekly_dict,
            issue_date=date(2026, 2, 9),
            html_template="weekly_digest_template.html",
            txt_template="weekly_digest_template.txt",
        )

        txt_path = path.parent / path.name.replace(".html", ".txt")
        assert txt_path.exists()
        txt_content = txt_path.read_text()
        assert "RIFLESSIONE SETTIMANALE" in txt_content
        assert "Weekly Title" in txt_content


class TestWeeklyTemplateRendering:
    """Tests for weekly digest template rendering output."""

    def test_html_template_renders_all_sections(
        self,
        sender: EmailSender,
        sample_weekly_dict: dict,
    ) -> None:
        """HTML template renders header, arcs, reflection, events, footer."""
        tpl = sender.jinja_env.get_template("weekly_digest_template.html")
        html = tpl.render(**sample_weekly_dict)

        # Header
        assert "BehindBars" in html
        assert "Digest Settimanale" in html
        assert "03.02 - 09.02.2026" in html

        # Title
        assert "Weekly Title" in html
        assert "Weekly Subtitle" in html

        # Arcs
        assert "Arc One" in html
        assert "Summary of arc one." in html
        assert "Arc Two" in html

        # Reflection
        assert "Riflessione Settimanale" in html
        assert "Reflection on the week." in html

        # Events
        assert "Eventi in Arrivo" in html
        assert "Voto Senato" in html
        assert "2026-02-15" in html

        # Quote + footer
        assert "civiltà" in html.lower()
        assert "Sardegna" in html

    def test_html_template_omits_subtitle_when_empty(
        self,
        sender: EmailSender,
        sample_weekly_dict: dict,
    ) -> None:
        """HTML template omits subtitle paragraph when empty."""
        sample_weekly_dict["weekly_subtitle"] = ""
        tpl = sender.jinja_env.get_template("weekly_digest_template.html")
        html = tpl.render(**sample_weekly_dict)

        # The <p class="newsletter-subtitle"> tag should not appear in the body
        assert '<p class="newsletter-subtitle">' not in html

    def test_html_template_omits_events_when_empty(
        self,
        sender: EmailSender,
        sample_weekly_dict: dict,
    ) -> None:
        """HTML template omits events section when list is empty."""
        sample_weekly_dict["upcoming_events"] = []
        tpl = sender.jinja_env.get_template("weekly_digest_template.html")
        html = tpl.render(**sample_weekly_dict)

        assert "Eventi in Arrivo" not in html

    def test_txt_template_renders_all_sections(
        self,
        sender: EmailSender,
        sample_weekly_dict: dict,
    ) -> None:
        """TXT template renders all sections with box-drawing characters."""
        tpl = sender.jinja_env.get_template("weekly_digest_template.txt")
        txt = tpl.render(**sample_weekly_dict)

        assert "BEHINDBARS" in txt
        assert "Digest Settimanale" in txt
        assert "Weekly Title" in txt
        assert "ARC ONE" in txt
        assert "Summary of arc one." in txt
        assert "RIFLESSIONE SETTIMANALE" in txt
        assert "Reflection on the week." in txt
        assert "EVENTI IN ARRIVO" in txt
        assert "Voto Senato" in txt
        assert "Sardegna" in txt

    def test_txt_template_omits_events_when_empty(
        self,
        sender: EmailSender,
        sample_weekly_dict: dict,
    ) -> None:
        """TXT template omits events section when list is empty."""
        sample_weekly_dict["upcoming_events"] = []
        tpl = sender.jinja_env.get_template("weekly_digest_template.txt")
        txt = tpl.render(**sample_weekly_dict)

        assert "EVENTI IN ARRIVO" not in txt

    def test_html_template_wraps_multiline_summary_in_paragraphs(
        self,
        sender: EmailSender,
        sample_weekly_dict: dict,
    ) -> None:
        """Multiline arc summary produces valid <p> tags."""
        sample_weekly_dict["narrative_arcs"] = [
            {"arc_title": "Test", "summary": "Primo paragrafo.\n\nSecondo paragrafo."},
        ]
        tpl = sender.jinja_env.get_template("weekly_digest_template.html")
        html = tpl.render(**sample_weekly_dict)

        assert "<p>Primo paragrafo.</p><p>Secondo paragrafo.</p>" in html

    def test_html_template_wraps_multiline_reflection_in_paragraphs(
        self,
        sender: EmailSender,
        sample_weekly_dict: dict,
    ) -> None:
        """Multiline weekly reflection produces valid <p> tags."""
        sample_weekly_dict["weekly_reflection"] = "Prima parte.\n\nSeconda parte."
        tpl = sender.jinja_env.get_template("weekly_digest_template.html")
        html = tpl.render(**sample_weekly_dict)

        assert "<p>Prima parte.</p><p>Seconda parte.</p>" in html
