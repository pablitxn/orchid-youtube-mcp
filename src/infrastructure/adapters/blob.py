"""Compatibility adapter over orchid_commons MultiBucketBlobRouter."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING, BinaryIO, Literal, cast

from orchid_commons.blob import BlobNotFoundError, MultiBucketBlobRouter
from orchid_commons.config.resources import MultiBucketSettings
from orchid_commons.runtime.health import HealthStatus

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Mapping
    from pathlib import Path

    from orchid_commons.blob.s3 import S3BlobStorage

_NOT_FOUND_CODES = {"NoSuchBucket", "NoSuchKey", "NotFound"}


class BlobStorageAdapter:
    """Adapter to keep youtube-mcp blob contract over commons router.

    The existing app contract passes a ``bucket`` on each call. ``orchid_commons``
    uses logical aliases and routes operations through ``MultiBucketBlobRouter``.
    This adapter resolves both alias names and physical bucket names to the router.
    """

    def __init__(
        self,
        *,
        router: MultiBucketBlobRouter,
        alias_to_bucket: Mapping[str, str] | None = None,
    ) -> None:
        self._router = router
        self._alias_to_bucket = (
            dict(alias_to_bucket)
            if alias_to_bucket is not None
            else dict(router.settings.buckets)
        )
        self._bucket_to_alias: dict[str, str] = {}
        for alias, bucket in self._alias_to_bucket.items():
            self._bucket_to_alias.setdefault(bucket, alias)

    @classmethod
    def from_settings(
        cls,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        buckets: Mapping[str, str],
        secure: bool = False,
        region: str | None = None,
        create_buckets_if_missing: bool = False,
    ) -> BlobStorageAdapter:
        """Build adapter directly from endpoint and alias bucket map."""
        try:
            from minio import Minio
        except ImportError as exc:  # pragma: no cover - optional dependency guard
            raise RuntimeError(
                "minio dependency is required for blob adapter construction"
            ) from exc

        settings = MultiBucketSettings(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            buckets=dict(buckets),
            create_buckets_if_missing=create_buckets_if_missing,
            secure=secure,
            region=region,
        )
        router = MultiBucketBlobRouter(
            client=Minio(**settings.to_s3_client_kwargs()),
            settings=settings,
        )
        return cls(router=router, alias_to_bucket=settings.buckets)

    def _resolve_alias(self, bucket: str) -> str:
        normalized = bucket.strip()
        if not normalized:
            raise ValueError("bucket must be a non-empty string")
        if normalized in self._alias_to_bucket:
            return normalized
        alias = self._bucket_to_alias.get(normalized)
        if alias is None:
            raise KeyError(f"Unknown bucket alias or name: {bucket!r}")
        return alias

    def _get_storage(self, alias: str) -> S3BlobStorage:
        return self._router.get_storage(alias)

    async def upload(
        self,
        bucket: str,
        path: str,
        data: BinaryIO | bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None,
    ) -> None:
        alias = self._resolve_alias(bucket)
        payload = data if isinstance(data, bytes) else bytes(data.read())

        await self._router.upload(
            alias,
            path,
            payload,
            content_type=content_type,
            metadata=metadata,
        )

    async def download(self, bucket: str, path: str) -> bytes:
        alias = self._resolve_alias(bucket)
        result = await self._router.download(alias, path)
        return cast("bytes", result.data)

    async def download_stream(
        self,
        bucket: str,
        path: str,
        chunk_size: int = 8192,
    ) -> AsyncIterator[bytes]:
        alias = self._resolve_alias(bucket)
        storage = self._get_storage(alias)
        physical_bucket = storage.bucket
        client = storage._client

        try:
            response = await asyncio.to_thread(client.get_object, physical_bucket, path)
        except Exception as exc:
            if getattr(exc, "code", None) in _NOT_FOUND_CODES:
                raise BlobNotFoundError(
                    "download", physical_bucket, path, str(exc)
                ) from exc
            raise

        try:
            while True:
                chunk: bytes = await asyncio.to_thread(response.read, chunk_size)
                if not chunk:
                    break
                yield chunk
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
            release_conn = getattr(response, "release_conn", None)
            if callable(release_conn):
                release_conn()

    async def download_to_file(
        self,
        bucket: str,
        path: str,
        local_path: Path,
        chunk_size: int = 8192,
    ) -> None:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        with local_path.open("wb") as f:
            async for chunk in self.download_stream(bucket, path, chunk_size):
                f.write(chunk)

    async def delete(self, bucket: str, path: str) -> bool:
        alias = self._resolve_alias(bucket)
        if not await self._router.exists(alias, path):
            return False
        await self._router.delete(alias, path)
        return True

    async def exists(self, bucket: str, path: str) -> bool:
        alias = self._resolve_alias(bucket)
        return cast("bool", await self._router.exists(alias, path))

    async def generate_presigned_url(
        self,
        bucket: str,
        path: str,
        expiry_seconds: int = 3600,
        method: str = "GET",
    ) -> str:
        alias = self._resolve_alias(bucket)
        normalized_method = method.upper()
        presign_method: Literal["GET", "PUT"]
        if normalized_method == "GET":
            presign_method = "GET"
        elif normalized_method == "PUT":
            presign_method = "PUT"
        else:
            raise ValueError("method must be GET or PUT")

        return cast(
            "str",
            await self._router.presign(
                alias,
                path,
                method=presign_method,
                expires=timedelta(seconds=expiry_seconds),
            ),
        )

    async def list_blobs(
        self,
        bucket: str,
        prefix: str = "",
        max_results: int = 1000,
    ) -> list[str]:
        alias = self._resolve_alias(bucket)
        storage = self._get_storage(alias)
        physical_bucket = storage.bucket
        client = storage._client

        def _list() -> list[str]:
            results: list[str] = []
            objects = client.list_objects(
                physical_bucket,
                prefix=prefix,
                recursive=True,
            )
            for obj in objects:
                results.append(obj.object_name)
                if len(results) >= max_results:
                    break
            return results

        return await asyncio.to_thread(_list)

    async def create_bucket(self, bucket: str) -> bool:
        alias = self._resolve_alias(bucket)
        storage = self._get_storage(alias)
        physical_bucket = storage.bucket
        client = storage._client

        if await asyncio.to_thread(client.bucket_exists, physical_bucket):
            return False

        try:
            await asyncio.to_thread(
                client.make_bucket,
                physical_bucket,
                location=self._router.settings.region,
            )
            return True
        except Exception:
            if await asyncio.to_thread(client.bucket_exists, physical_bucket):
                return False
            raise

    async def bucket_exists(self, bucket: str) -> bool:
        alias = self._resolve_alias(bucket)
        storage = self._get_storage(alias)
        return await asyncio.to_thread(
            storage._client.bucket_exists,
            storage.bucket,
        )

    async def health_check(self) -> HealthStatus:
        status = await self._router.health_check()
        details = None
        if status.details is not None:
            details = {k: str(v) for k, v in status.details.items()}
        return HealthStatus(
            healthy=status.healthy,
            latency_ms=status.latency_ms,
            message=status.message,
            details=details,
        )

    async def close(self) -> None:
        """Close underlying router resources."""
        await self._router.close()
