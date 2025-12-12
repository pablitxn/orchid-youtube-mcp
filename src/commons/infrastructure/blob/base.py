"""Abstract base class for blob storage operations."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO


@dataclass
class BlobMetadata:
    """Metadata for a stored blob."""

    path: str
    size_bytes: int
    content_type: str
    created_at: datetime
    etag: str


@dataclass
class HealthStatus:
    """Health check result."""

    healthy: bool
    latency_ms: float
    message: str | None = None
    details: dict[str, str] | None = None


class BlobStorageBase(ABC):
    """Abstract base class for blob storage operations.

    Implementations should handle:
    - MinIO (local development)
    - AWS S3
    - Google Cloud Storage
    - Azure Blob Storage
    """

    @abstractmethod
    async def upload(
        self,
        bucket: str,
        path: str,
        data: BinaryIO | bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> BlobMetadata:
        """Upload a blob to storage.

        Args:
            bucket: Target bucket name.
            path: Path within the bucket.
            data: File-like object or bytes to upload.
            content_type: MIME type of the content.
            metadata: Optional key-value metadata.

        Returns:
            Metadata of the uploaded blob.
        """

    @abstractmethod
    async def download(self, bucket: str, path: str) -> bytes:
        """Download a blob from storage.

        Args:
            bucket: Source bucket name.
            path: Path within the bucket.

        Returns:
            Blob content as bytes.

        Raises:
            BlobNotFoundError: If blob doesn't exist.
        """

    @abstractmethod
    def download_stream(
        self,
        bucket: str,
        path: str,
        chunk_size: int = 8192,
    ) -> AsyncIterator[bytes]:
        """Stream download a blob in chunks.

        Args:
            bucket: Source bucket name.
            path: Path within the bucket.
            chunk_size: Size of each chunk in bytes.

        Yields:
            Chunks of blob content.
        """
        ...

    @abstractmethod
    async def download_to_file(
        self,
        bucket: str,
        path: str,
        local_path: Path,
        chunk_size: int = 8192,
    ) -> None:
        """Download a blob to a local file using streaming.

        This method downloads the blob in chunks to avoid loading
        the entire file into memory, making it suitable for large files.

        Args:
            bucket: Source bucket name.
            path: Path within the bucket.
            local_path: Local filesystem path to write to.
            chunk_size: Size of each chunk in bytes.

        Raises:
            BlobNotFoundError: If blob doesn't exist.
        """

    @abstractmethod
    async def delete(self, bucket: str, path: str) -> bool:
        """Delete a blob from storage.

        Args:
            bucket: Bucket name.
            path: Path within the bucket.

        Returns:
            True if deleted, False if didn't exist.
        """

    @abstractmethod
    async def exists(self, bucket: str, path: str) -> bool:
        """Check if a blob exists.

        Args:
            bucket: Bucket name.
            path: Path within the bucket.

        Returns:
            True if exists, False otherwise.
        """

    @abstractmethod
    async def get_metadata(self, bucket: str, path: str) -> BlobMetadata:
        """Get blob metadata without downloading.

        Args:
            bucket: Bucket name.
            path: Path within the bucket.

        Returns:
            Blob metadata.

        Raises:
            BlobNotFoundError: If blob doesn't exist.
        """

    @abstractmethod
    async def generate_presigned_url(
        self,
        bucket: str,
        path: str,
        expiry_seconds: int = 3600,
        method: str = "GET",
    ) -> str:
        """Generate a presigned URL for direct access.

        Args:
            bucket: Bucket name.
            path: Path within the bucket.
            expiry_seconds: URL validity duration.
            method: HTTP method (GET or PUT).

        Returns:
            Presigned URL string.
        """

    @abstractmethod
    async def list_blobs(
        self,
        bucket: str,
        prefix: str = "",
        max_results: int = 1000,
    ) -> list[BlobMetadata]:
        """List blobs with optional prefix filter.

        Args:
            bucket: Bucket name.
            prefix: Filter by path prefix.
            max_results: Maximum number of results.

        Returns:
            List of blob metadata.
        """

    @abstractmethod
    async def create_bucket(self, bucket: str) -> bool:
        """Create a new bucket.

        Args:
            bucket: Bucket name to create.

        Returns:
            True if created, False if already exists.
        """

    @abstractmethod
    async def bucket_exists(self, bucket: str) -> bool:
        """Check if a bucket exists.

        Args:
            bucket: Bucket name.

        Returns:
            True if exists, False otherwise.
        """

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Check service health.

        Returns:
            Health status with latency info.
        """
