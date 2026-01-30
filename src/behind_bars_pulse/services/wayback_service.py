# ABOUTME: Service for archiving article URLs to the Wayback Machine.
# ABOUTME: Provides fire-and-forget async archival for article preservation.

import asyncio
from urllib.parse import quote

import httpx
import structlog

logger = structlog.get_logger()

WAYBACK_SAVE_URL = "https://web.archive.org/save/"
WAYBACK_AVAILABILITY_URL = "https://archive.org/wayback/available"


class WaybackService:
    """Service for archiving URLs to the Internet Archive's Wayback Machine."""

    def __init__(self, timeout: float = 30.0) -> None:
        self.timeout = timeout

    async def archive_url(self, url: str) -> str | None:
        """Archive a URL to the Wayback Machine.

        Args:
            url: The URL to archive

        Returns:
            The archived URL if successful, None otherwise
        """
        save_url = f"{WAYBACK_SAVE_URL}{quote(url, safe='')}"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(save_url, follow_redirects=True)

                if response.status_code in (200, 302):
                    # Extract archived URL from response headers or location
                    archived_url = response.headers.get(
                        "Content-Location",
                        response.headers.get("Location"),
                    )
                    if archived_url:
                        if not archived_url.startswith("http"):
                            archived_url = f"https://web.archive.org{archived_url}"
                        logger.info("url_archived", url=url, archived_url=archived_url)
                        return archived_url

                logger.warning(
                    "archive_unexpected_response",
                    url=url,
                    status=response.status_code,
                )
                return None

        except httpx.TimeoutException:
            logger.warning("archive_timeout", url=url)
            return None
        except Exception as e:
            logger.error("archive_failed", url=url, error=str(e))
            return None

    async def check_availability(self, url: str) -> str | None:
        """Check if a URL is already archived.

        Args:
            url: The URL to check

        Returns:
            The archived URL if available, None otherwise
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    WAYBACK_AVAILABILITY_URL,
                    params={"url": url},
                )

                if response.status_code == 200:
                    data = response.json()
                    snapshots = data.get("archived_snapshots", {})
                    closest = snapshots.get("closest")
                    if closest and closest.get("available"):
                        return closest.get("url")

                return None

        except Exception as e:
            logger.debug("availability_check_failed", url=url, error=str(e))
            return None

    async def archive_urls_background(
        self,
        urls: list[str],
        delay_between: float = 1.0,
    ) -> None:
        """Archive multiple URLs in the background with rate limiting.

        This is a fire-and-forget method that doesn't block the caller.
        Failures are logged but don't raise exceptions.

        Args:
            urls: List of URLs to archive
            delay_between: Seconds to wait between archival requests
        """
        for url in urls:
            try:
                # Check if already archived recently
                existing = await self.check_availability(url)
                if existing:
                    logger.debug("url_already_archived", url=url)
                    continue

                await self.archive_url(url)
                await asyncio.sleep(delay_between)

            except Exception as e:
                logger.error("background_archive_failed", url=url, error=str(e))
                continue

    def schedule_archival(self, urls: list[str]) -> asyncio.Task:
        """Schedule URLs for background archival.

        Returns an asyncio Task that can be awaited if needed,
        but typically this is fire-and-forget.

        Args:
            urls: List of URLs to archive

        Returns:
            asyncio.Task for the background archival operation
        """
        return asyncio.create_task(
            self.archive_urls_background(urls),
            name="wayback_archival",
        )
