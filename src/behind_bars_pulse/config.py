# ABOUTME: Centralized configuration using Pydantic Settings.
# ABOUTME: Loads all settings from environment variables and .env file.

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # AI / Vertex AI
    gcp_project: str = "wishew-gemini-test"
    gcp_location: str = "global"
    gemini_model: str = "gemini-3-flash-preview"
    gemini_fallback_model: str = "gemini-3-flash-preview"
    ai_sleep_between_calls: int = 30
    ai_temperature: float = 1.0
    ai_top_p: float = 0.95
    ai_max_output_tokens: int = 8192

    # Feeds
    feed_url: str = "https://ristretti.org/index.php?format=feed&type=rss"
    feed_timeout: int = 10
    max_articles: int = 100  # Collect all, AI selects best for newsletter
    max_newsletter_articles: int = 12  # Max articles in final newsletter
    feed_user_agent: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.3 Safari/605.1.15"
    )

    # Email / SES (optional - only required for send commands)
    smtp_host: str = "email-smtp.eu-west-1.amazonaws.com"
    smtp_port: int = 587
    ses_usr: SecretStr | None = None
    ses_pwd: SecretStr | None = None
    sender_email: str = "behindbars@iungomail.com"
    sender_name: str = "Behind Bars Pulse"
    bounce_email: str = "bounces@iungomail.com"
    confirmation_email_subject: str = "Conferma la tua iscrizione a BehindBars"
    default_recipient: str = "maroffo@gmail.com"

    # Database (optional - only required for web and DB persistence)
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "behindbars"
    db_user: str = "behindbars"
    db_password: SecretStr | None = None
    db_pool_size: int = 5
    db_pool_max_overflow: int = 10

    @property
    def database_url(self) -> str:
        """Build async PostgreSQL connection URL."""
        password = self.db_password.get_secret_value() if self.db_password else ""
        return f"postgresql+asyncpg://{self.db_user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"

    @property
    def database_url_sync(self) -> str:
        """Build sync PostgreSQL connection URL (for Alembic)."""
        password = self.db_password.get_secret_value() if self.db_password else ""
        return (
            f"postgresql://{self.db_user}:{password}@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    # Paths
    previous_issues_dir: Path = Path("previous_issues")
    templates_dir: Path = Path("src/behind_bars_pulse/email/templates")
    data_dir: Path = Path("data")

    # Narrative memory
    narrative_context_file: str = "narrative_context.json"
    story_archive_days: int = 90
    context_token_budget: int = 4000
    weekly_lookback_days: int = 7
    min_story_mentions_for_weekly: int = 2

    # Logging
    log_level: str = "INFO"
    log_format: str = "console"  # "console" or "json"

    # Web / API
    app_base_url: str = "http://localhost:8000"  # Base URL for email links
    scheduler_audience: str = ""  # OIDC audience for Cloud Scheduler verification


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance.

    Settings are loaded from environment variables and .env file.
    SES credentials (ses_usr, ses_pwd) are optional - only required for email sending.
    """
    return Settings()
