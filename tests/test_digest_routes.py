# ABOUTME: Tests for digest web routes, edizioni digest archive, and RSS feed.
# ABOUTME: Verifies route handlers with mocked repository dependencies.

from datetime import date, datetime
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient


def _make_digest(
    *,
    week_start: date = date(2026, 2, 3),
    week_end: date = date(2026, 2, 9),
    title: str = "Settimana di tensione",
    subtitle: str | None = "Sovraffollamento e riforme",
    narrative_arcs: list | None = None,
    weekly_reflection: str | None = "Una riflessione profonda.",
    upcoming_events: list | None = None,
):
    """Create a mock WeeklyDigest object."""
    from unittest.mock import MagicMock

    digest = MagicMock()
    digest.week_start = week_start
    digest.week_end = week_end
    digest.title = title
    digest.subtitle = subtitle
    digest.narrative_arcs = narrative_arcs or [
        {"arc_title": "Sovraffollamento", "summary": "Le carceri sono **piene**."},
    ]
    digest.weekly_reflection = weekly_reflection
    digest.upcoming_events = upcoming_events or [
        {"event": "Audizione al Senato", "date": "2026-02-15"},
    ]
    digest.created_at = datetime(2026, 2, 9, 12, 0, 0)
    return digest


@pytest.fixture
def mock_digest_repo():
    """Create a mock WeeklyDigestRepository."""
    repo = AsyncMock()
    repo.get_latest = AsyncMock(return_value=None)
    repo.get_by_week_end = AsyncMock(return_value=None)
    repo.get_previous = AsyncMock(return_value=None)
    repo.get_next = AsyncMock(return_value=None)
    repo.list_recent = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_bulletin_repo():
    """Create a mock BulletinRepository."""
    repo = AsyncMock()
    repo.list_recent = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def mock_newsletter_repo():
    """Create a mock NewsletterRepository."""
    repo = AsyncMock()
    repo.list_recent = AsyncMock(return_value=[])
    return repo


@pytest.fixture
def client(mock_digest_repo, mock_bulletin_repo, mock_newsletter_repo):
    """Create a test client with mocked dependencies."""
    from behind_bars_pulse.web.app import create_app
    from behind_bars_pulse.web.dependencies import (
        get_bulletin_repository,
        get_newsletter_repository,
        get_weekly_digest_repository,
    )

    with (
        patch("behind_bars_pulse.web.app.init_db", new_callable=AsyncMock),
        patch("behind_bars_pulse.web.app.close_db", new_callable=AsyncMock),
    ):
        app = create_app()

    app.dependency_overrides[get_weekly_digest_repository] = lambda: mock_digest_repo
    app.dependency_overrides[get_bulletin_repository] = lambda: mock_bulletin_repo
    app.dependency_overrides[get_newsletter_repository] = lambda: mock_newsletter_repo

    return TestClient(app, raise_server_exceptions=False)


class TestDigestLatest:
    """Tests for GET /digest (latest digest)."""

    def test_empty_state_when_no_digests(self, client, mock_digest_repo):
        """Should render empty template when no digests exist."""
        mock_digest_repo.get_latest.return_value = None

        response = client.get("/digest")

        assert response.status_code == 200
        assert "Nessun digest disponibile" in response.text

    def test_shows_latest_digest(self, client, mock_digest_repo):
        """Should render the latest digest."""
        digest = _make_digest()
        mock_digest_repo.get_latest.return_value = digest
        mock_digest_repo.get_previous.return_value = None

        response = client.get("/digest")

        assert response.status_code == 200
        assert "Settimana di tensione" in response.text
        assert "Sovraffollamento e riforme" in response.text

    def test_shows_navigation_to_previous(self, client, mock_digest_repo):
        """Should show link to previous digest when available."""
        digest = _make_digest()
        prev_digest = _make_digest(
            week_start=date(2026, 1, 27),
            week_end=date(2026, 2, 2),
            title="Settimana precedente",
        )
        mock_digest_repo.get_latest.return_value = digest
        mock_digest_repo.get_previous.return_value = prev_digest

        response = client.get("/digest")

        assert response.status_code == 200
        assert "/digest/2026-02-02" in response.text


class TestDigestDetail:
    """Tests for GET /digest/{date_str}."""

    def test_valid_date_shows_digest(self, client, mock_digest_repo):
        """Should render digest for valid date."""
        digest = _make_digest()
        mock_digest_repo.get_by_week_end.return_value = digest
        mock_digest_repo.get_previous.return_value = None
        mock_digest_repo.get_next.return_value = None

        response = client.get("/digest/2026-02-09")

        assert response.status_code == 200
        assert "Settimana di tensione" in response.text

    def test_invalid_date_returns_400(self, client):
        """Should return 400 for invalid date format."""
        response = client.get("/digest/not-a-date")

        assert response.status_code == 400

    def test_missing_digest_returns_404(self, client, mock_digest_repo):
        """Should return 404 when digest not found."""
        mock_digest_repo.get_by_week_end.return_value = None

        response = client.get("/digest/2026-02-09")

        assert response.status_code == 404

    def test_shows_narrative_arcs(self, client, mock_digest_repo):
        """Should render narrative arcs section."""
        digest = _make_digest(
            narrative_arcs=[
                {"arc_title": "Sovraffollamento", "summary": "Le carceri sono piene."},
                {"arc_title": "Riforme", "summary": "Nuove proposte in parlamento."},
            ]
        )
        mock_digest_repo.get_by_week_end.return_value = digest

        response = client.get("/digest/2026-02-09")

        assert response.status_code == 200
        assert "Sovraffollamento" in response.text
        assert "Riforme" in response.text

    def test_shows_weekly_reflection(self, client, mock_digest_repo):
        """Should render weekly reflection section."""
        digest = _make_digest(weekly_reflection="Riflessione sulla settimana.")
        mock_digest_repo.get_by_week_end.return_value = digest

        response = client.get("/digest/2026-02-09")

        assert response.status_code == 200
        assert "Riflessione Settimanale" in response.text

    def test_shows_upcoming_events(self, client, mock_digest_repo):
        """Should render upcoming events section."""
        digest = _make_digest(
            upcoming_events=[
                {"event": "Audizione al Senato", "date": "2026-02-15"},
            ]
        )
        mock_digest_repo.get_by_week_end.return_value = digest

        response = client.get("/digest/2026-02-09")

        assert response.status_code == 200
        assert "Eventi in Arrivo" in response.text
        assert "Audizione al Senato" in response.text

    def test_navigation_with_prev_and_next(self, client, mock_digest_repo):
        """Should render prev/next navigation links."""
        digest = _make_digest()
        prev = _make_digest(week_start=date(2026, 1, 27), week_end=date(2026, 2, 2))
        nxt = _make_digest(week_start=date(2026, 2, 10), week_end=date(2026, 2, 16))
        mock_digest_repo.get_by_week_end.return_value = digest
        mock_digest_repo.get_previous.return_value = prev
        mock_digest_repo.get_next.return_value = nxt

        response = client.get("/digest/2026-02-09")

        assert response.status_code == 200
        assert "/digest/2026-02-02" in response.text
        assert "/digest/2026-02-16" in response.text


class TestDigestArchiveRedirect:
    """Tests for GET /digest/archivio."""

    def test_redirects_to_edizioni_digest(self, client):
        """Should redirect /digest/archivio to /edizioni/digest."""
        response = client.get("/digest/archivio", follow_redirects=False)

        assert response.status_code == 301
        assert "/edizioni/digest" in response.headers["location"]

    def test_redirect_preserves_page_param(self, client):
        """Should preserve page parameter in redirect."""
        response = client.get("/digest/archivio?page=3", follow_redirects=False)

        assert response.status_code == 301
        assert "page=3" in response.headers["location"]


class TestEdizioniDigestArchive:
    """Tests for GET /edizioni/digest."""

    def test_empty_archive(self, client, mock_digest_repo):
        """Should show empty state when no digests."""
        mock_digest_repo.list_recent.return_value = []

        response = client.get("/edizioni/digest")

        assert response.status_code == 200
        assert "Nessun digest disponibile" in response.text

    def test_archive_lists_digests(self, client, mock_digest_repo):
        """Should list digests in archive."""
        digests = [
            _make_digest(),
            _make_digest(
                week_start=date(2026, 1, 27),
                week_end=date(2026, 2, 2),
                title="Settimana precedente",
            ),
        ]
        mock_digest_repo.list_recent.return_value = digests

        response = client.get("/edizioni/digest")

        assert response.status_code == 200
        assert "Settimana di tensione" in response.text
        assert "Settimana precedente" in response.text


class TestEdizioniOverviewWithDigests:
    """Tests for GET /edizioni including digests."""

    def test_overview_passes_digests(self, client, mock_digest_repo):
        """Should include digests in overview context."""
        digests = [_make_digest()]
        mock_digest_repo.list_recent.return_value = digests

        response = client.get("/edizioni")

        assert response.status_code == 200
        # The edizioni.html template doesn't render digests yet (WS3),
        # but the route should not error
        mock_digest_repo.list_recent.assert_called_once_with(limit=5)


class TestDigestFeed:
    """Tests for GET /feed/digest RSS feed."""

    def test_empty_feed(self, client, mock_digest_repo):
        """Should return valid RSS with no items."""
        mock_digest_repo.list_recent.return_value = []

        response = client.get("/feed/digest")

        assert response.status_code == 200
        assert "application/rss+xml" in response.headers["content-type"]
        assert "Digest Settimanale - BehindBars" in response.text
        assert "<item>" not in response.text

    def test_feed_with_digests(self, client, mock_digest_repo):
        """Should include digest items in RSS feed."""
        digests = [
            _make_digest(),
            _make_digest(
                week_start=date(2026, 1, 27),
                week_end=date(2026, 2, 2),
                title="Settimana precedente",
                subtitle="Sottotitolo precedente",
            ),
        ]
        mock_digest_repo.list_recent.return_value = digests

        response = client.get("/feed/digest")

        assert response.status_code == 200
        assert "<item>" in response.text
        assert "Settimana di tensione" in response.text
        assert "Settimana precedente" in response.text
        assert "/digest/2026-02-09" in response.text
        assert "/digest/2026-02-02" in response.text

    def test_feed_uses_subtitle_as_description(self, client, mock_digest_repo):
        """Should use subtitle as RSS item description."""
        digests = [_make_digest(subtitle="Un sottotitolo specifico")]
        mock_digest_repo.list_recent.return_value = digests

        response = client.get("/feed/digest")

        assert response.status_code == 200
        assert "Un sottotitolo specifico" in response.text

    def test_feed_fallback_description(self, client, mock_digest_repo):
        """Should use fallback description when subtitle is None."""
        digests = [_make_digest(subtitle=None)]
        mock_digest_repo.list_recent.return_value = digests

        response = client.get("/feed/digest")

        assert response.status_code == 200
        assert "Riepilogo settimanale" in response.text
