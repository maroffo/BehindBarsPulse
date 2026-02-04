# ABOUTME: Storage service for GCS integration.
# ABOUTME: Handles persistent storage of newsletters and data files.

from pathlib import Path

import structlog
from google.cloud import storage

log = structlog.get_logger()


class StorageService:
    """Service for storing and retrieving files from GCS."""

    def __init__(self, bucket_name: str | None = None):
        """Initialize storage service.

        Args:
            bucket_name: GCS bucket name. If None, GCS is disabled.
        """
        self.bucket_name = bucket_name
        self._client: storage.Client | None = None
        self._bucket: storage.Bucket | None = None

        if bucket_name:
            try:
                self._client = storage.Client()
                self._bucket = self._client.bucket(bucket_name)
                log.info("gcs_storage_initialized", bucket=bucket_name)
            except Exception as e:
                log.warning("gcs_storage_init_failed", error=str(e))
                self._client = None
                self._bucket = None

    @property
    def is_enabled(self) -> bool:
        """Check if GCS storage is enabled and working."""
        return self._bucket is not None

    def upload_file(self, local_path: Path, gcs_path: str) -> str | None:
        """Upload a file to GCS.

        Args:
            local_path: Local file path.
            gcs_path: Destination path in GCS (e.g., "previous_issues/file.html").

        Returns:
            GCS URI if successful, None otherwise.
        """
        if not self.is_enabled:
            return None

        try:
            blob = self._bucket.blob(gcs_path)
            blob.upload_from_filename(str(local_path))
            uri = f"gs://{self.bucket_name}/{gcs_path}"
            log.info("file_uploaded_to_gcs", local=str(local_path), gcs=uri)
            return uri
        except Exception as e:
            log.error("gcs_upload_failed", error=str(e), path=gcs_path)
            return None

    def upload_content(
        self, content: str, gcs_path: str, content_type: str = "text/plain"
    ) -> str | None:
        """Upload string content directly to GCS.

        Args:
            content: String content to upload.
            gcs_path: Destination path in GCS.
            content_type: MIME type of the content.

        Returns:
            GCS URI if successful, None otherwise.
        """
        if not self.is_enabled:
            return None

        try:
            blob = self._bucket.blob(gcs_path)
            blob.upload_from_string(content, content_type=content_type)
            uri = f"gs://{self.bucket_name}/{gcs_path}"
            log.info("content_uploaded_to_gcs", gcs=uri)
            return uri
        except Exception as e:
            log.error("gcs_upload_failed", error=str(e), path=gcs_path)
            return None

    def download_content(self, gcs_path: str) -> str | None:
        """Download content from GCS.

        Args:
            gcs_path: Path in GCS.

        Returns:
            File content as string, or None if failed.
        """
        if not self.is_enabled:
            return None

        try:
            blob = self._bucket.blob(gcs_path)
            return blob.download_as_text()
        except Exception as e:
            log.error("gcs_download_failed", error=str(e), path=gcs_path)
            return None

    def list_files(self, prefix: str) -> list[str]:
        """List files in GCS with given prefix.

        Args:
            prefix: Path prefix (e.g., "previous_issues/").

        Returns:
            List of file paths.
        """
        if not self.is_enabled:
            return []

        try:
            blobs = self._client.list_blobs(self.bucket_name, prefix=prefix)
            return [blob.name for blob in blobs]
        except Exception as e:
            log.error("gcs_list_failed", error=str(e), prefix=prefix)
            return []
