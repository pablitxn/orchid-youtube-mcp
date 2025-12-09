"""MinIO implementation of blob storage."""

import asyncio
import io
import time
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import BinaryIO

from minio import Minio
from minio.error import S3Error

from src.commons.infrastructure.blob.base import (
    BlobMetadata,
    BlobStorageBase,
    HealthStatus,
)


class BlobNotFoundError(Exception):
    """Raised when a blob is not found."""

    def __init__(self, bucket: str, path: str) -> None:
        self.bucket = bucket
        self.path = path
        super().__init__(f"Blob not found: {bucket}/{path}")


class MinioBlobStorage(BlobStorageBase):
    """MinIO implementation of blob storage.

    Works with both MinIO (local development) and AWS S3 (production).
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        secure: bool = False,
        region: str | None = None,
    ) -> None:
        """Initialize MinIO client.

        Args:
            endpoint: MinIO/S3 endpoint (e.g., "localhost:9000").
            access_key: Access key ID.
            secret_key: Secret access key.
            secure: Use HTTPS connection.
            region: AWS region (optional, for S3).
        """
        self._client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
        )
        self._endpoint = endpoint
        self._secure = secure

    async def upload(
        self,
        bucket: str,
        path: str,
        data: BinaryIO | bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> BlobMetadata:
        """Upload a blob to storage."""
        loop = asyncio.get_event_loop()

        if isinstance(data, bytes):
            data_io: BinaryIO = io.BytesIO(data)
            length = len(data)
        else:
            data.seek(0, io.SEEK_END)
            length = data.tell()
            data.seek(0)
            data_io = data

        def _upload() -> None:
            self._client.put_object(
                bucket_name=bucket,
                object_name=path,
                data=data_io,
                length=length,
                content_type=content_type,
                metadata=metadata,
            )

        await loop.run_in_executor(None, _upload)
        return await self.get_metadata(bucket, path)

    async def download(self, bucket: str, path: str) -> bytes:
        """Download a blob from storage."""
        loop = asyncio.get_event_loop()

        def _download() -> bytes:
            try:
                response = self._client.get_object(bucket, path)
                try:
                    data: bytes = response.read()
                    return data
                finally:
                    response.close()
                    response.release_conn()
            except S3Error as e:
                if e.code == "NoSuchKey":
                    raise BlobNotFoundError(bucket, path) from e
                raise

        return await loop.run_in_executor(None, _download)

    async def download_stream(  # type: ignore[override]
        self,
        bucket: str,
        path: str,
        chunk_size: int = 8192,
    ) -> AsyncIterator[bytes]:
        """Stream download a blob in chunks."""
        loop = asyncio.get_event_loop()

        try:
            response = await loop.run_in_executor(
                None, self._client.get_object, bucket, path
            )
        except S3Error as e:
            if e.code == "NoSuchKey":
                raise BlobNotFoundError(bucket, path) from e
            raise

        try:
            while True:
                chunk: bytes = await loop.run_in_executor(
                    None, response.read, chunk_size
                )
                if not chunk:
                    break
                yield chunk
        finally:
            response.close()
            response.release_conn()

    async def delete(self, bucket: str, path: str) -> bool:
        """Delete a blob from storage."""
        loop = asyncio.get_event_loop()

        exists = await self.exists(bucket, path)
        if not exists:
            return False

        def _delete() -> None:
            self._client.remove_object(bucket, path)

        await loop.run_in_executor(None, _delete)
        return True

    async def exists(self, bucket: str, path: str) -> bool:
        """Check if a blob exists."""
        loop = asyncio.get_event_loop()

        def _stat() -> bool:
            try:
                self._client.stat_object(bucket, path)
                return True
            except S3Error as e:
                if e.code == "NoSuchKey":
                    return False
                raise

        return await loop.run_in_executor(None, _stat)

    async def get_metadata(self, bucket: str, path: str) -> BlobMetadata:
        """Get blob metadata without downloading."""
        loop = asyncio.get_event_loop()

        def _stat() -> BlobMetadata:
            try:
                stat = self._client.stat_object(bucket, path)
                return BlobMetadata(
                    path=path,
                    size_bytes=stat.size or 0,
                    content_type=stat.content_type or "application/octet-stream",
                    created_at=stat.last_modified or datetime.now(UTC),
                    etag=stat.etag or "",
                )
            except S3Error as e:
                if e.code == "NoSuchKey":
                    raise BlobNotFoundError(bucket, path) from e
                raise

        return await loop.run_in_executor(None, _stat)

    async def generate_presigned_url(
        self,
        bucket: str,
        path: str,
        expiry_seconds: int = 3600,
        method: str = "GET",
    ) -> str:
        """Generate a presigned URL for direct access."""
        loop = asyncio.get_event_loop()
        from datetime import timedelta

        def _presign() -> str:
            if method.upper() == "PUT":
                url = self._client.presigned_put_object(
                    bucket_name=bucket,
                    object_name=path,
                    expires=timedelta(seconds=expiry_seconds),
                )
                return str(url)
            url = self._client.presigned_get_object(
                bucket_name=bucket,
                object_name=path,
                expires=timedelta(seconds=expiry_seconds),
            )
            return str(url)

        return await loop.run_in_executor(None, _presign)

    async def list_blobs(
        self,
        bucket: str,
        prefix: str = "",
        max_results: int = 1000,
    ) -> list[BlobMetadata]:
        """List blobs with optional prefix filter."""
        loop = asyncio.get_event_loop()

        def _list() -> list[BlobMetadata]:
            objects = self._client.list_objects(
                bucket_name=bucket,
                prefix=prefix,
                recursive=True,
            )
            results: list[BlobMetadata] = []
            for obj in objects:
                if len(results) >= max_results:
                    break
                results.append(
                    BlobMetadata(
                        path=obj.object_name or "",
                        size_bytes=obj.size or 0,
                        content_type="application/octet-stream",
                        created_at=obj.last_modified or datetime.now(UTC),
                        etag=obj.etag or "",
                    )
                )
            return results

        return await loop.run_in_executor(None, _list)

    async def create_bucket(self, bucket: str) -> bool:
        """Create a new bucket."""
        loop = asyncio.get_event_loop()

        def _create() -> bool:
            if self._client.bucket_exists(bucket):
                return False
            self._client.make_bucket(bucket)
            return True

        return await loop.run_in_executor(None, _create)

    async def bucket_exists(self, bucket: str) -> bool:
        """Check if a bucket exists."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._client.bucket_exists, bucket)

    async def health_check(self) -> HealthStatus:
        """Check service health."""
        start = time.perf_counter()
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._client.list_buckets)
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthStatus(
                healthy=True,
                latency_ms=latency_ms,
                message="MinIO is healthy",
                details={"endpoint": self._endpoint},
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthStatus(
                healthy=False,
                latency_ms=latency_ms,
                message=f"MinIO health check failed: {e}",
                details={"endpoint": self._endpoint, "error": str(e)},
            )
