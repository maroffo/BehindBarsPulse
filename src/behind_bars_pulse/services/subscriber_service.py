# ABOUTME: Service for managing newsletter subscriptions.
# ABOUTME: Handles subscriber creation, confirmation, unsubscription with double opt-in.

import secrets
from datetime import UTC, datetime

import structlog

from behind_bars_pulse.db.models import Subscriber
from behind_bars_pulse.db.repository import SubscriberRepository

log = structlog.get_logger()


class SubscriberService:
    """Service for managing newsletter subscriptions."""

    def __init__(self, repo: SubscriberRepository) -> None:
        self.repo = repo

    async def create_subscriber(self, email: str) -> Subscriber:
        """Create a new subscriber or resubscribe an unsubscribed one.

        Args:
            email: Email address to subscribe.

        Returns:
            The new or reactivated subscriber.

        Raises:
            ValueError: If email is already subscribed and confirmed.
        """
        email = email.strip().lower()

        existing = await self.repo.get_by_email(email)

        if existing:
            if existing.unsubscribed_at:
                # Resubscribe: reset unsubscribed_at, generate new token, require re-confirmation
                log.info("resubscribing", email=email)
                existing.unsubscribed_at = None
                existing.confirmed = False
                existing.confirmed_at = None
                existing.token = self._generate_token()
                return await self.repo.save(existing)
            elif existing.confirmed:
                log.warning("already_subscribed", email=email)
                raise ValueError(f"Email {email} is already subscribed")
            else:
                # Pending confirmation - just return existing (they can use same link)
                log.info("subscription_pending", email=email)
                return existing

        # New subscriber
        subscriber = Subscriber(
            email=email,
            token=self._generate_token(),
            confirmed=False,
            subscribed_at=datetime.now(tz=UTC),
        )
        saved = await self.repo.save(subscriber)
        log.info("subscriber_created", email=email, id=saved.id)
        return saved

    async def confirm_subscriber(self, token: str) -> Subscriber | None:
        """Confirm a subscriber using their token.

        Args:
            token: The confirmation token.

        Returns:
            The confirmed subscriber, or None if token not found.
        """
        subscriber = await self.repo.get_by_token(token)

        if not subscriber:
            log.warning("confirm_invalid_token", token=token[:8] + "...")
            return None

        if subscriber.confirmed:
            log.info("already_confirmed", email=subscriber.email)
            return subscriber

        subscriber.confirmed = True
        subscriber.confirmed_at = datetime.now(tz=UTC)
        await self.repo.save(subscriber)

        log.info("subscriber_confirmed", email=subscriber.email)
        return subscriber

    async def unsubscribe(self, token: str) -> Subscriber | None:
        """Unsubscribe using the subscriber's token.

        Args:
            token: The unsubscribe token.

        Returns:
            The unsubscribed subscriber, or None if token not found.
        """
        subscriber = await self.repo.get_by_token(token)

        if not subscriber:
            log.warning("unsubscribe_invalid_token", token=token[:8] + "...")
            return None

        if subscriber.unsubscribed_at:
            log.info("already_unsubscribed", email=subscriber.email)
            return subscriber

        subscriber.unsubscribed_at = datetime.now(tz=UTC)
        await self.repo.save(subscriber)

        log.info("subscriber_unsubscribed", email=subscriber.email)
        return subscriber

    async def get_active_subscribers(self) -> list[Subscriber]:
        """Get all active subscribers (confirmed and not unsubscribed).

        Returns:
            List of active subscribers.
        """
        subscribers = await self.repo.list_active()
        return list(subscribers)

    async def get_active_emails(self) -> list[str]:
        """Get email addresses of all active subscribers.

        Returns:
            List of email addresses.
        """
        subscribers = await self.get_active_subscribers()
        return [s.email for s in subscribers]

    def _generate_token(self) -> str:
        """Generate a secure random token for confirmation/unsubscribe."""
        return secrets.token_hex(16)  # 32 chars
