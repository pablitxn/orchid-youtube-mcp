"""Unit tests for BlobStorageAdapter."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from orchid_commons.blob.s3 import BlobObject
from orchid_commons.runtime.health import HealthStatus as CommonsHealthStatus

from src.infrastructure.adapters.blob import BlobStorageAdapter


@pytest.fixture
def router_fixture():
    settings = SimpleNamespace(
        buckets={
            "videos": "rag-videos",
            "chunks": "rag-chunks",
            "frames": "rag-frames",
        },
        region="us-east-1",
    )

    storages: dict[str, SimpleNamespace] = {}
    for alias, bucket in settings.buckets.items():
        client = MagicMock()
        client.stat_object.return_value = SimpleNamespace(
            size=123,
            content_type="application/octet-stream",
            last_modified=datetime.now(UTC),
            etag=f"etag-{alias}",
        )
        client.list_objects.return_value = []
        client.bucket_exists.return_value = True
        storages[alias] = SimpleNamespace(bucket=bucket, _client=client)

    router = MagicMock()
    router.settings = settings
    router.get_storage.side_effect = lambda alias: storages[alias]
    router.upload = AsyncMock()
    router.download = AsyncMock(
        return_value=BlobObject(
            key="video-1/video.mp4",
            data=b"video-bytes",
            content_type="video/mp4",
        )
    )
    router.exists = AsyncMock(return_value=True)
    router.delete = AsyncMock()
    router.presign = AsyncMock(return_value="https://signed.example.com/url")
    router.health_check = AsyncMock(
        return_value=CommonsHealthStatus(
            healthy=True,
            latency_ms=5.0,
            message="ok",
            details={"aliases": ["videos", "chunks", "frames"]},
        )
    )
    router.close = AsyncMock()

    return {"router": router, "storages": storages}


class TestBlobStorageAdapter:
    @pytest.mark.asyncio
    async def test_upload_routes_physical_bucket_to_alias(self, router_fixture):
        router = router_fixture["router"]

        adapter = BlobStorageAdapter(router=router)
        await adapter.upload(
            "rag-videos",
            "video-1/video.mp4",
            b"video-bytes",
            content_type="video/mp4",
        )

        router.upload.assert_awaited_once_with(
            "videos",
            "video-1/video.mp4",
            b"video-bytes",
            content_type="video/mp4",
            metadata=None,
        )

    @pytest.mark.asyncio
    async def test_download_routes_alias(self, router_fixture):
        router = router_fixture["router"]

        adapter = BlobStorageAdapter(router=router)
        data = await adapter.download("videos", "video-1/video.mp4")

        assert data == b"video-bytes"
        router.download.assert_awaited_once_with("videos", "video-1/video.mp4")

    @pytest.mark.asyncio
    async def test_delete_returns_false_when_missing(self, router_fixture):
        router = router_fixture["router"]
        router.exists.return_value = False

        adapter = BlobStorageAdapter(router=router)
        deleted = await adapter.delete("rag-frames", "video-1/frames/frame_00001.jpg")

        assert deleted is False
        router.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_routes_and_returns_true_when_found(self, router_fixture):
        router = router_fixture["router"]
        router.exists.return_value = True

        adapter = BlobStorageAdapter(router=router)
        deleted = await adapter.delete("rag-frames", "video-1/frames/frame_00001.jpg")

        assert deleted is True
        router.delete.assert_awaited_once_with(
            "frames",
            "video-1/frames/frame_00001.jpg",
        )

    @pytest.mark.asyncio
    async def test_presign_routes_with_expiry(self, router_fixture):
        router = router_fixture["router"]

        adapter = BlobStorageAdapter(router=router)
        url = await adapter.generate_presigned_url(
            "rag-chunks",
            "video-1/chunks/chunk_0001.json",
            expiry_seconds=120,
            method="PUT",
        )

        assert url == "https://signed.example.com/url"
        router.presign.assert_awaited_once_with(
            "chunks",
            "video-1/chunks/chunk_0001.json",
            method="PUT",
            expires=timedelta(seconds=120),
        )

    @pytest.mark.asyncio
    async def test_list_blobs_routes_to_bucket(self, router_fixture):
        storages = router_fixture["storages"]

        storages["chunks"]._client.list_objects.return_value = [
            SimpleNamespace(
                object_name="video-1/chunks/chunk_0001.json",
                size=42,
                content_type="application/json",
                last_modified=datetime(2026, 1, 1, tzinfo=UTC),
                etag="abc123",
            ),
            SimpleNamespace(
                object_name="video-1/chunks/chunk_0002.json",
                size=43,
                content_type="application/json",
                last_modified=datetime(2026, 1, 1, tzinfo=UTC),
                etag="def456",
            ),
        ]

        adapter = BlobStorageAdapter(router=router_fixture["router"])
        blobs = await adapter.list_blobs(
            "rag-chunks",
            prefix="video-1/chunks/",
            max_results=1,
        )

        assert len(blobs) == 1
        assert blobs[0] == "video-1/chunks/chunk_0001.json"
        storages["chunks"]._client.list_objects.assert_called_once_with(
            "rag-chunks",
            prefix="video-1/chunks/",
            recursive=True,
        )

    @pytest.mark.asyncio
    async def test_unknown_bucket_raises_key_error(self, router_fixture):
        adapter = BlobStorageAdapter(router=router_fixture["router"])

        with pytest.raises(KeyError, match="Unknown bucket alias or name"):
            await adapter.exists("non-existent-bucket", "video.mp4")
