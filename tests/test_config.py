# ABOUTME: Tests for configuration loading and validation.
# ABOUTME: Verifies Pydantic Settings behavior and defaults.

from pathlib import Path

from pydantic import SecretStr

from behind_bars_pulse.config import Settings


class TestSettings:
    """Tests for Settings configuration class."""

    def test_settings_with_required_fields(self, tmp_path: Path) -> None:
        """Settings should load with required fields provided."""
        settings = Settings(
            ses_usr=SecretStr("test-user"),
            ses_pwd=SecretStr("test-password"),
            previous_issues_dir=tmp_path,
        )

        assert settings.gcp_project == "wishew-gemini-test"
        assert settings.gcp_location == "global"
        assert settings.gemini_model == "gemini-3-flash-preview"
        assert settings.ses_usr.get_secret_value() == "test-user"

    def test_settings_default_values(self, mock_settings: Settings) -> None:
        """Settings should have correct default values."""
        assert mock_settings.ai_sleep_between_calls == 0  # overridden in fixture
        assert mock_settings.feed_timeout == 5
        assert mock_settings.smtp_port == 1025

    def test_settings_ses_credentials_optional(self) -> None:
        """Settings should allow missing SES credentials for non-email commands."""
        settings = Settings()
        assert settings.ses_usr is None
        assert settings.ses_pwd is None

    def test_settings_secret_values_hidden(self, mock_settings: Settings) -> None:
        """Secret values should not be exposed in string representation."""
        settings_str = str(mock_settings)
        assert "test-user" not in settings_str
        assert "test-password" not in settings_str

    def test_settings_paths_are_path_objects(self, mock_settings: Settings) -> None:
        """Path settings should be Path objects."""
        assert isinstance(mock_settings.previous_issues_dir, Path)
        assert isinstance(mock_settings.templates_dir, Path)
