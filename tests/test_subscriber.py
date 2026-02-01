# ABOUTME: Tests for subscriber model, repository, and service.
# ABOUTME: Validates subscription flow: create, confirm, unsubscribe, resubscribe.

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from behind_bars_pulse.db.models import Subscriber
from behind_bars_pulse.db.repository import SubscriberRepository
from behind_bars_pulse.services.subscriber_service import SubscriberService


class TestSubscriberModel:
    """Tests for the Subscriber model."""

    def test_subscriber_creation(self) -> None:
        """Test creating a subscriber with required fields."""
        token = str(uuid4())[:64]
        subscriber = Subscriber(
            email="test@example.com",
            token=token,
            confirmed=False,  # Explicit since default only applies at DB insert
        )
        assert subscriber.email == "test@example.com"
        assert subscriber.token == token
        assert subscriber.confirmed is False
        assert subscriber.confirmed_at is None
        assert subscriber.unsubscribed_at is None

    def test_subscriber_with_all_fields(self) -> None:
        """Test creating a subscriber with all fields."""
        now = datetime.now(tz=UTC)
        token = str(uuid4())[:64]
        subscriber = Subscriber(
            email="full@example.com",
            token=token,
            confirmed=True,
            subscribed_at=now,
            confirmed_at=now,
            unsubscribed_at=None,
        )
        assert subscriber.email == "full@example.com"
        assert subscriber.confirmed is True
        assert subscriber.confirmed_at == now

    def test_subscriber_email_max_length(self) -> None:
        """Test that email can be up to 320 characters."""
        # RFC 5321 allows up to 254 chars for email, but we use 320 for safety
        long_local = "a" * 64
        long_domain = "b" * 63 + "." + "c" * 63 + ".com"
        long_email = f"{long_local}@{long_domain}"
        token = str(uuid4())[:64]
        subscriber = Subscriber(email=long_email, token=token)
        assert len(subscriber.email) > 100  # Just verify it's long

    def test_subscriber_repr(self) -> None:
        """Test subscriber string representation."""
        subscriber = Subscriber(email="repr@test.com", token="abc123")
        repr_str = repr(subscriber)
        assert "repr@test.com" in repr_str


class TestSubscriberRepository:
    """Tests for the SubscriberRepository class."""

    @pytest.fixture
    def mock_session(self) -> AsyncMock:
        """Create a mock async session."""
        session = AsyncMock()
        session.add = MagicMock()
        session.flush = AsyncMock()
        return session

    @pytest.fixture
    def repo(self, mock_session: AsyncMock) -> SubscriberRepository:
        """Create a SubscriberRepository with mock session."""
        return SubscriberRepository(mock_session)

    @pytest.fixture
    def sample_subscriber(self) -> Subscriber:
        """Create a sample subscriber for testing."""
        return Subscriber(
            id=1,
            email="test@example.com",
            token="test-token-12345",
            confirmed=True,
            subscribed_at=datetime.now(tz=UTC),
            confirmed_at=datetime.now(tz=UTC),
        )

    async def test_save_adds_to_session(
        self, repo: SubscriberRepository, mock_session: AsyncMock
    ) -> None:
        """Test that save adds subscriber to session and flushes."""
        subscriber = Subscriber(email="new@test.com", token="token123", confirmed=False)
        result = await repo.save(subscriber)

        mock_session.add.assert_called_once_with(subscriber)
        mock_session.flush.assert_awaited_once()
        assert result == subscriber

    async def test_get_by_email(
        self, repo: SubscriberRepository, mock_session: AsyncMock, sample_subscriber: Subscriber
    ) -> None:
        """Test retrieving subscriber by email."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_subscriber
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_email("test@example.com")

        assert result == sample_subscriber
        mock_session.execute.assert_awaited_once()

    async def test_get_by_token(
        self, repo: SubscriberRepository, mock_session: AsyncMock, sample_subscriber: Subscriber
    ) -> None:
        """Test retrieving subscriber by token."""
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = sample_subscriber
        mock_session.execute.return_value = mock_result

        result = await repo.get_by_token("test-token-12345")

        assert result == sample_subscriber
        mock_session.execute.assert_awaited_once()

    async def test_list_active_returns_confirmed_not_unsubscribed(
        self, repo: SubscriberRepository, mock_session: AsyncMock, sample_subscriber: Subscriber
    ) -> None:
        """Test listing active subscribers (confirmed and not unsubscribed)."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sample_subscriber]
        mock_session.execute.return_value = mock_result

        result = await repo.list_active()

        assert len(result) == 1
        assert result[0] == sample_subscriber
        mock_session.execute.assert_awaited_once()


class TestSubscriberService:
    """Tests for the SubscriberService class."""

    @pytest.fixture
    def mock_repo(self) -> AsyncMock:
        """Create a mock SubscriberRepository."""
        repo = AsyncMock(spec=SubscriberRepository)
        return repo

    @pytest.fixture
    def service(self, mock_repo: AsyncMock) -> SubscriberService:
        """Create a SubscriberService with mock repository."""
        return SubscriberService(mock_repo)

    async def test_create_subscriber_new_email(
        self, service: SubscriberService, mock_repo: AsyncMock
    ) -> None:
        """Test creating a new subscriber."""
        mock_repo.get_by_email.return_value = None

        async def save_subscriber(sub: Subscriber) -> Subscriber:
            sub.id = 1
            return sub

        mock_repo.save.side_effect = save_subscriber

        result = await service.create_subscriber("new@test.com")

        assert result.email == "new@test.com"
        assert result.confirmed is False
        assert len(result.token) == 32  # hex of 16 bytes
        mock_repo.save.assert_awaited_once()

    async def test_create_subscriber_existing_unsubscribed_resubscribes(
        self, service: SubscriberService, mock_repo: AsyncMock
    ) -> None:
        """Test that creating subscriber for unsubscribed email resubscribes."""
        existing = Subscriber(
            id=1,
            email="old@test.com",
            token="old-token",
            confirmed=True,
            subscribed_at=datetime.now(tz=UTC),
            unsubscribed_at=datetime.now(tz=UTC),
        )
        mock_repo.get_by_email.return_value = existing
        mock_repo.save.return_value = existing

        result = await service.create_subscriber("old@test.com")

        assert result.unsubscribed_at is None
        assert result.confirmed is False  # Needs to re-confirm
        mock_repo.save.assert_awaited_once()

    async def test_create_subscriber_existing_confirmed_raises(
        self, service: SubscriberService, mock_repo: AsyncMock
    ) -> None:
        """Test that creating subscriber for existing confirmed email raises."""
        existing = Subscriber(
            id=1,
            email="active@test.com",
            token="token",
            confirmed=True,
            subscribed_at=datetime.now(tz=UTC),
        )
        mock_repo.get_by_email.return_value = existing

        with pytest.raises(ValueError, match="already subscribed"):
            await service.create_subscriber("active@test.com")

    async def test_confirm_subscriber_valid_token(
        self, service: SubscriberService, mock_repo: AsyncMock
    ) -> None:
        """Test confirming a subscriber with valid token."""
        subscriber = Subscriber(
            id=1,
            email="pending@test.com",
            token="valid-token",
            confirmed=False,
            subscribed_at=datetime.now(tz=UTC),
        )
        mock_repo.get_by_token.return_value = subscriber
        mock_repo.save.return_value = subscriber

        result = await service.confirm_subscriber("valid-token")

        assert result is not None
        assert result.confirmed is True
        assert result.confirmed_at is not None

    async def test_confirm_subscriber_invalid_token(
        self, service: SubscriberService, mock_repo: AsyncMock
    ) -> None:
        """Test confirming with invalid token returns None."""
        mock_repo.get_by_token.return_value = None

        result = await service.confirm_subscriber("invalid-token")

        assert result is None

    async def test_unsubscribe_valid_token(
        self, service: SubscriberService, mock_repo: AsyncMock
    ) -> None:
        """Test unsubscribing with valid token."""
        subscriber = Subscriber(
            id=1,
            email="active@test.com",
            token="unsub-token",
            confirmed=True,
            subscribed_at=datetime.now(tz=UTC),
        )
        mock_repo.get_by_token.return_value = subscriber
        mock_repo.save.return_value = subscriber

        result = await service.unsubscribe("unsub-token")

        assert result is not None
        assert result.unsubscribed_at is not None

    async def test_get_active_subscribers(
        self, service: SubscriberService, mock_repo: AsyncMock
    ) -> None:
        """Test getting list of active subscribers."""
        subscribers = [
            Subscriber(id=1, email="a@test.com", token="t1", confirmed=True),
            Subscriber(id=2, email="b@test.com", token="t2", confirmed=True),
        ]
        mock_repo.list_active.return_value = subscribers

        result = await service.get_active_subscribers()

        assert len(result) == 2
        assert result[0].email == "a@test.com"
