# ABOUTME: Tests for _run_weekly background task in API routes.
# ABOUTME: Validates WeeklyDigest DB save, email context, and template params.

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from behind_bars_pulse.newsletter.weekly import WeeklyDigestContent


@pytest.fixture
def sample_weekly_content() -> WeeklyDigestContent:
    """Sample WeeklyDigestContent for testing."""
    return WeeklyDigestContent(
        weekly_title="Titolo Settimanale",
        weekly_subtitle="Sottotitolo",
        narrative_arcs=[{"arc_title": "Arco 1", "summary": "Riassunto arco."}],
        weekly_reflection="Riflessione settimanale.",
        upcoming_events=[{"event": "Evento futuro", "date": "2026-02-20"}],
    )


@pytest.fixture
def mock_db_env():
    """Set up mock DB environment for _run_weekly tests.

    Patches SQLAlchemy engine, sessions, and settings to avoid real DB access.
    Returns a namespace with all mock objects for assertion.
    """
    mock_engine = MagicMock()

    # Session from sessionmaker (for bulletin/recipient queries)
    mock_query_session = MagicMock()
    mock_query_session.__enter__ = MagicMock(return_value=mock_query_session)
    mock_query_session.__exit__ = MagicMock(return_value=False)

    # Session from Session(engine) (for digest save)
    mock_save_session = MagicMock()
    mock_save_session.__enter__ = MagicMock(return_value=mock_save_session)
    mock_save_session.__exit__ = MagicMock(return_value=False)
    mock_save_session.query.return_value.filter.return_value.first.return_value = None

    mock_sessionmaker_instance = MagicMock(return_value=mock_query_session)

    mock_settings = MagicMock()
    mock_settings.database_url = "postgresql+asyncpg://localhost/test"
    mock_settings.weekly_lookback_days = 7

    with (
        patch("sqlalchemy.create_engine", return_value=mock_engine) as p_engine,
        patch("sqlalchemy.orm.sessionmaker", return_value=mock_sessionmaker_instance),
        patch("sqlalchemy.orm.Session", return_value=mock_save_session) as p_session,
        patch("behind_bars_pulse.config.get_settings", return_value=mock_settings),
    ):
        yield SimpleNamespace(
            engine=mock_engine,
            query_session=mock_query_session,
            save_session=mock_save_session,
            settings=mock_settings,
            p_engine=p_engine,
            p_session=p_session,
        )


def _setup_query_results(mock_query_session, bulletins, recipients):
    """Configure session.execute() to return bulletins and recipients."""
    mock_result_bulletins = MagicMock()
    mock_result_bulletins.scalars.return_value.all.return_value = bulletins

    mock_result_recipients = MagicMock()
    mock_result_recipients.scalars.return_value.all.return_value = recipients

    mock_query_session.execute.side_effect = [
        mock_result_bulletins,
        mock_result_recipients,
    ]


class TestRunWeekly:
    """Tests for _run_weekly background task."""

    @patch("behind_bars_pulse.email.sender.EmailSender")
    @patch("behind_bars_pulse.newsletter.weekly.WeeklyDigestGenerator")
    def test_uses_build_email_context(
        self,
        mock_generator_cls: MagicMock,
        mock_sender_cls: MagicMock,
        mock_db_env,
        sample_weekly_content: WeeklyDigestContent,
    ) -> None:
        """_run_weekly calls build_email_context instead of build_context."""
        mock_generator = MagicMock()
        mock_generator.settings.weekly_lookback_days = 7
        mock_generator.generate.return_value = sample_weekly_content
        mock_generator.build_email_context.return_value = {"subject": "Test Subject"}
        mock_generator_cls.return_value = mock_generator
        mock_sender_cls.return_value = MagicMock()

        bulletins = [SimpleNamespace(issue_date=date(2026, 2, 4))]
        _setup_query_results(mock_db_env.query_session, bulletins, ["a@b.com"])

        from behind_bars_pulse.web.routes.api import _run_weekly

        _run_weekly(date(2026, 2, 10))

        mock_generator.build_email_context.assert_called_once()
        mock_generator.build_context.assert_not_called()

    @patch("behind_bars_pulse.email.sender.EmailSender")
    @patch("behind_bars_pulse.newsletter.weekly.WeeklyDigestGenerator")
    def test_passes_weekly_templates_to_sender(
        self,
        mock_generator_cls: MagicMock,
        mock_sender_cls: MagicMock,
        mock_db_env,
        sample_weekly_content: WeeklyDigestContent,
    ) -> None:
        """_run_weekly passes weekly digest template names to sender.send()."""
        mock_generator = MagicMock()
        mock_generator.settings.weekly_lookback_days = 7
        mock_generator.generate.return_value = sample_weekly_content
        mock_generator.build_email_context.return_value = {"subject": "Test"}
        mock_generator_cls.return_value = mock_generator

        mock_sender = MagicMock()
        mock_sender_cls.return_value = mock_sender

        bulletins = [SimpleNamespace(issue_date=date(2026, 2, 4))]
        _setup_query_results(mock_db_env.query_session, bulletins, ["a@b.com", "c@d.com"])

        from behind_bars_pulse.web.routes.api import _run_weekly

        _run_weekly(date(2026, 2, 10))

        mock_sender.send.assert_called_once()
        call_kwargs = mock_sender.send.call_args
        assert call_kwargs.kwargs["html_template"] == "weekly_digest_template.html"
        assert call_kwargs.kwargs["txt_template"] == "weekly_digest_template.txt"

    @patch("behind_bars_pulse.email.sender.EmailSender")
    @patch("behind_bars_pulse.newsletter.weekly.WeeklyDigestGenerator")
    def test_saves_weekly_digest_to_db(
        self,
        mock_generator_cls: MagicMock,
        mock_sender_cls: MagicMock,
        mock_db_env,
        sample_weekly_content: WeeklyDigestContent,
    ) -> None:
        """_run_weekly saves WeeklyDigest to database via Session."""
        mock_generator = MagicMock()
        mock_generator.settings.weekly_lookback_days = 7
        mock_generator.generate.return_value = sample_weekly_content
        mock_generator.build_email_context.return_value = {"subject": "Test"}
        mock_generator_cls.return_value = mock_generator
        mock_sender_cls.return_value = MagicMock()

        bulletins = [SimpleNamespace(issue_date=date(2026, 2, 4))]
        _setup_query_results(mock_db_env.query_session, bulletins, ["a@b.com"])

        from behind_bars_pulse.web.routes.api import _run_weekly

        _run_weekly(date(2026, 2, 10))

        # Verify digest was added and committed
        mock_db_env.save_session.add.assert_called_once()
        mock_db_env.save_session.commit.assert_called()

    @patch("behind_bars_pulse.newsletter.weekly.WeeklyDigestGenerator")
    def test_no_bulletins_returns_early(
        self,
        mock_generator_cls: MagicMock,
        mock_db_env,
    ) -> None:
        """_run_weekly returns early when no bulletins found."""
        mock_generator = MagicMock()
        mock_generator.settings.weekly_lookback_days = 7
        mock_generator_cls.return_value = mock_generator

        _setup_query_results(mock_db_env.query_session, [], ["a@b.com"])

        from behind_bars_pulse.web.routes.api import _run_weekly

        _run_weekly(date(2026, 2, 10))

        mock_generator.generate.assert_not_called()
        mock_db_env.engine.dispose.assert_called_once()

    @patch("behind_bars_pulse.email.sender.EmailSender")
    @patch("behind_bars_pulse.newsletter.weekly.WeeklyDigestGenerator")
    def test_no_recipients_skips_send_but_saves_digest(
        self,
        mock_generator_cls: MagicMock,
        mock_sender_cls: MagicMock,
        mock_db_env,
        sample_weekly_content: WeeklyDigestContent,
    ) -> None:
        """_run_weekly skips sending when no recipients but still saves digest."""
        mock_generator = MagicMock()
        mock_generator.settings.weekly_lookback_days = 7
        mock_generator.generate.return_value = sample_weekly_content
        mock_generator.build_email_context.return_value = {"subject": "Test"}
        mock_generator_cls.return_value = mock_generator

        mock_sender = MagicMock()
        mock_sender_cls.return_value = mock_sender

        bulletins = [SimpleNamespace(issue_date=date(2026, 2, 4))]
        _setup_query_results(mock_db_env.query_session, bulletins, [])

        from behind_bars_pulse.web.routes.api import _run_weekly

        _run_weekly(date(2026, 2, 10))

        # Digest should still be saved
        mock_db_env.save_session.add.assert_called_once()
        mock_db_env.save_session.commit.assert_called()
        # But sender.send should NOT be called
        mock_sender.send.assert_not_called()

    @patch("behind_bars_pulse.email.sender.EmailSender")
    @patch("behind_bars_pulse.newsletter.weekly.WeeklyDigestGenerator")
    def test_deletes_existing_digest_before_save(
        self,
        mock_generator_cls: MagicMock,
        mock_sender_cls: MagicMock,
        mock_db_env,
        sample_weekly_content: WeeklyDigestContent,
    ) -> None:
        """_run_weekly deletes existing digest for same week_end before saving new one."""
        mock_generator = MagicMock()
        mock_generator.settings.weekly_lookback_days = 7
        mock_generator.generate.return_value = sample_weekly_content
        mock_generator.build_email_context.return_value = {"subject": "Test"}
        mock_generator_cls.return_value = mock_generator
        mock_sender_cls.return_value = MagicMock()

        bulletins = [SimpleNamespace(issue_date=date(2026, 2, 4))]
        _setup_query_results(mock_db_env.query_session, bulletins, ["a@b.com"])

        # Simulate existing digest
        existing_digest = MagicMock()
        mock_db_env.save_session.query.return_value.filter.return_value.first.return_value = (
            existing_digest
        )

        from behind_bars_pulse.web.routes.api import _run_weekly

        _run_weekly(date(2026, 2, 10))

        # Should delete existing and then add new
        mock_db_env.save_session.delete.assert_called_once_with(existing_digest)
        mock_db_env.save_session.add.assert_called_once()
