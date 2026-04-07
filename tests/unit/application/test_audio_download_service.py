"""Unit tests for the audio batch download service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from src.application.dtos.audio_download import (
    AudioDownloadBatchRequest,
    AudioDownloadBatchStatus,
)
from src.application.services.audio_download import AudioDownloadBatchService
from src.infrastructure.youtube.base import YouTubeMetadata

if TYPE_CHECKING:
    from pathlib import Path


class _StubDownloader:
    """Test double for bounded-concurrency verification."""

    def __init__(self) -> None:
        self.current = 0
        self.max_seen = 0

    def validate_url(self, url: str) -> bool:
        return url.startswith("https://")

    async def download_audio_only(
        self,
        url: str,
        output_dir: Path,
        audio_format: str = "mp3",
        audio_quality: str = "192",
    ) -> tuple[Path, YouTubeMetadata]:
        del audio_quality
        self.current += 1
        self.max_seen = max(self.max_seen, self.current)
        await asyncio.sleep(0.05)
        self.current -= 1

        video_id = url.rsplit("=", maxsplit=1)[-1]
        return (
            output_dir / f"{video_id}.{audio_format}",
            YouTubeMetadata(
                id=video_id,
                title=f"Title {video_id}",
                description="",
                duration_seconds=60,
                channel_name="channel",
                channel_id="channel-id",
                upload_date=datetime.now(UTC),
                thumbnail_url="https://example.com/thumb.jpg",
                view_count=0,
                like_count=None,
            ),
        )


@pytest.mark.asyncio
async def test_audio_batch_respects_max_concurrency(tmp_path: Path) -> None:
    """The scheduler should never run more than 3 downloads simultaneously."""
    downloader = _StubDownloader()
    service = AudioDownloadBatchService(
        youtube_downloader=downloader,
        default_output_dir=tmp_path,
    )

    request = AudioDownloadBatchRequest(
        youtube_urls=[
            f"https://youtube.com/watch?v=video{i:02d}" for i in range(8)
        ],
        max_concurrent_downloads=3,
    )

    job = await service.submit_batch(request)

    while True:
        snapshot = await service.get_batch(job.job_id)
        assert snapshot is not None
        if snapshot.status in {
            AudioDownloadBatchStatus.COMPLETED,
            AudioDownloadBatchStatus.COMPLETED_WITH_ERRORS,
        }:
            break
        await asyncio.sleep(0.02)

    assert downloader.max_seen <= 3
    assert snapshot.completed_items == 8
    assert snapshot.failed_items == 0
