# ABOUTME: Tests for run_weekly_pipeline shared pipeline function.
# ABOUTME: Validates data loading, generation, DB save (atomic), and result structure.

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from behind_bars_pulse.newsletter.weekly import WeeklyDigestContent, WeeklyPipelineResult


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
    """Set up mock DB environment for run_weekly_pipeline tests.

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
        patch("sqlalchemy.create_engine", return_value=mock_engine),
        patch("sqlalchemy.orm.sessionmaker", return_value=mock_sessionmaker_instance),
        patch("sqlalchemy.orm.Session", return_value=mock_save_session),
        patch("behind_bars_pulse.config.get_settings", return_value=mock_settings),
    ):
        yield SimpleNamespace(
            engine=mock_engine,
            query_session=mock_query_session,
            save_session=mock_save_session,
            settings=mock_settings,
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


class TestRunWeeklyPipeline:
    """Tests for run_weekly_pipeline shared function."""

    @patch("behind_bars_pulse.newsletter.weekly.WeeklyDigestGenerator")
    def test_returns_pipeline_result(
        self,
        mock_generator_cls: MagicMock,
        mock_db_env,
        sample_weekly_content: WeeklyDigestContent,
    ) -> None:
        """run_weekly_pipeline returns a WeeklyPipelineResult."""
        mock_generator = MagicMock()
        mock_generator.settings.weekly_lookback_days = 7
        mock_generator.generate.return_value = sample_weekly_content
        mock_generator.build_email_context.return_value = {"subject": "Test Subject"}
        mock_generator_cls.return_value = mock_generator

        bulletins = [SimpleNamespace(issue_date=date(2026, 2, 4))]
        _setup_query_results(mock_db_env.query_session, bulletins, ["a@b.com"])

        from behind_bars_pulse.newsletter.weekly import run_weekly_pipeline

        result = run_weekly_pipeline(date(2026, 2, 10))

        assert isinstance(result, WeeklyPipelineResult)
        assert result.content is sample_weekly_content
        assert result.email_context == {"subject": "Test Subject"}
        assert result.recipients == ["a@b.com"]
        assert result.week_start == date(2026, 2, 4)
        assert result.week_end == date(2026, 2, 10)

    @patch("behind_bars_pulse.newsletter.weekly.WeeklyDigestGenerator")
    def test_calls_build_email_context(
        self,
        mock_generator_cls: MagicMock,
        mock_db_env,
        sample_weekly_content: WeeklyDigestContent,
    ) -> None:
        """run_weekly_pipeline calls build_email_context (not build_context)."""
        mock_generator = MagicMock()
        mock_generator.settings.weekly_lookback_days = 7
        mock_generator.generate.return_value = sample_weekly_content
        mock_generator.build_email_context.return_value = {"subject": "Test"}
        mock_generator_cls.return_value = mock_generator

        bulletins = [SimpleNamespace(issue_date=date(2026, 2, 4))]
        _setup_query_results(mock_db_env.query_session, bulletins, ["a@b.com"])

        from behind_bars_pulse.newsletter.weekly import run_weekly_pipeline

        run_weekly_pipeline(date(2026, 2, 10))

        mock_generator.build_email_context.assert_called_once()
        mock_generator.build_context.assert_not_called()

    @patch("behind_bars_pulse.newsletter.weekly.WeeklyDigestGenerator")
    def test_saves_digest_to_db(
        self,
        mock_generator_cls: MagicMock,
        mock_db_env,
        sample_weekly_content: WeeklyDigestContent,
    ) -> None:
        """run_weekly_pipeline saves WeeklyDigest to database."""
        mock_generator = MagicMock()
        mock_generator.settings.weekly_lookback_days = 7
        mock_generator.generate.return_value = sample_weekly_content
        mock_generator.build_email_context.return_value = {"subject": "Test"}
        mock_generator_cls.return_value = mock_generator

        bulletins = [SimpleNamespace(issue_date=date(2026, 2, 4))]
        _setup_query_results(mock_db_env.query_session, bulletins, ["a@b.com"])

        from behind_bars_pulse.newsletter.weekly import run_weekly_pipeline

        run_weekly_pipeline(date(2026, 2, 10))

        mock_db_env.save_session.add.assert_called_once()
        mock_db_env.save_session.commit.assert_called_once()

    @patch("behind_bars_pulse.newsletter.weekly.WeeklyDigestGenerator")
    def test_atomic_delete_and_save(
        self,
        mock_generator_cls: MagicMock,
        mock_db_env,
        sample_weekly_content: WeeklyDigestContent,
    ) -> None:
        """run_weekly_pipeline deletes existing + adds new in single commit."""
        mock_generator = MagicMock()
        mock_generator.settings.weekly_lookback_days = 7
        mock_generator.generate.return_value = sample_weekly_content
        mock_generator.build_email_context.return_value = {"subject": "Test"}
        mock_generator_cls.return_value = mock_generator

        bulletins = [SimpleNamespace(issue_date=date(2026, 2, 4))]
        _setup_query_results(mock_db_env.query_session, bulletins, ["a@b.com"])

        # Simulate existing digest
        existing_digest = MagicMock()
        mock_db_env.save_session.query.return_value.filter.return_value.first.return_value = (
            existing_digest
        )

        from behind_bars_pulse.newsletter.weekly import run_weekly_pipeline

        run_weekly_pipeline(date(2026, 2, 10))

        mock_db_env.save_session.delete.assert_called_once_with(existing_digest)
        mock_db_env.save_session.add.assert_called_once()
        # Only one commit: delete + add are atomic
        mock_db_env.save_session.commit.assert_called_once()

    @patch("behind_bars_pulse.newsletter.weekly.WeeklyDigestGenerator")
    def test_no_bulletins_raises_value_error(
        self,
        mock_generator_cls: MagicMock,
        mock_db_env,
    ) -> None:
        """run_weekly_pipeline raises ValueError when no bulletins found."""
        mock_generator = MagicMock()
        mock_generator.settings.weekly_lookback_days = 7
        mock_generator.generate.side_effect = ValueError("No bulletins found for weekly digest")
        mock_generator_cls.return_value = mock_generator

        _setup_query_results(mock_db_env.query_session, [], ["a@b.com"])

        from behind_bars_pulse.newsletter.weekly import run_weekly_pipeline

        with pytest.raises(ValueError, match="No bulletins"):
            run_weekly_pipeline(date(2026, 2, 10))

    @patch("behind_bars_pulse.newsletter.weekly.WeeklyDigestGenerator")
    def test_empty_recipients_returned(
        self,
        mock_generator_cls: MagicMock,
        mock_db_env,
        sample_weekly_content: WeeklyDigestContent,
    ) -> None:
        """run_weekly_pipeline returns empty recipients (callers decide what to do)."""
        mock_generator = MagicMock()
        mock_generator.settings.weekly_lookback_days = 7
        mock_generator.generate.return_value = sample_weekly_content
        mock_generator.build_email_context.return_value = {"subject": "Test"}
        mock_generator_cls.return_value = mock_generator

        bulletins = [SimpleNamespace(issue_date=date(2026, 2, 4))]
        _setup_query_results(mock_db_env.query_session, bulletins, [])

        from behind_bars_pulse.newsletter.weekly import run_weekly_pipeline

        result = run_weekly_pipeline(date(2026, 2, 10))

        assert result.recipients == []
        # Digest should still be saved
        mock_db_env.save_session.add.assert_called_once()

    @patch("behind_bars_pulse.newsletter.weekly.WeeklyDigestGenerator")
    def test_engine_disposed_on_success(
        self,
        mock_generator_cls: MagicMock,
        mock_db_env,
        sample_weekly_content: WeeklyDigestContent,
    ) -> None:
        """run_weekly_pipeline disposes engine after successful run."""
        mock_generator = MagicMock()
        mock_generator.settings.weekly_lookback_days = 7
        mock_generator.generate.return_value = sample_weekly_content
        mock_generator.build_email_context.return_value = {"subject": "Test"}
        mock_generator_cls.return_value = mock_generator

        bulletins = [SimpleNamespace(issue_date=date(2026, 2, 4))]
        _setup_query_results(mock_db_env.query_session, bulletins, ["a@b.com"])

        from behind_bars_pulse.newsletter.weekly import run_weekly_pipeline

        run_weekly_pipeline(date(2026, 2, 10))

        mock_db_env.engine.dispose.assert_called_once()
