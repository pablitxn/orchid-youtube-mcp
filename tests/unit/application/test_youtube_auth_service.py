"""Unit tests for the managed YouTube audio download state machine."""

from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.dtos.youtube_auth import (
    AudioDownloadPreset,
    AudioDownloadState,
    PreparedYouTubeAudioDownload,
    SavedYouTubeAudioDownload,
    YouTubeAuthMode,
    YouTubeAuthStatus,
)
from src.application.services.youtube_auth import (
    AudioDownloadStateConflictError,
    YouTubeAuthService,
)


@pytest.fixture
def mock_settings():
    """Create minimal settings for the YouTube auth service."""
    settings = MagicMock()
    settings.document_db.collections.app_state = "app_state"
    settings.youtube.managed_cookies_file = "/tmp/youtube-auth/cookies.txt"
    settings.youtube.managed_cookies_encryption_key = ""
    settings.blob_storage.buckets.videos = "videos"
    return settings


@pytest.fixture
def mock_document_db():
    """Create a mocked document store adapter."""
    document_db = AsyncMock()
    document_db.insert.return_value = "download-1"
    document_db.update.return_value = True
    document_db.update_many.return_value = 0
    document_db.delete.return_value = True
    return document_db


@pytest.fixture
def mock_factory():
    """Create a mocked infrastructure factory."""
    factory = MagicMock()
    factory.get_blob_storage.return_value = AsyncMock()
    factory.get_youtube_downloader.return_value = MagicMock()
    return factory


@pytest.fixture
def service(mock_document_db, mock_factory, mock_settings):
    """Create the service under test."""
    return YouTubeAuthService(
        document_db=mock_document_db,
        factory=mock_factory,
        settings=mock_settings,
    )


class TestYouTubeAuthService:
    """Tests for persisted audio download states."""

    @pytest.mark.asyncio
    async def test_create_saved_audio_download_queues_job(
        self,
        service,
        mock_document_db,
        mock_factory,
    ):
        """Queue a new persisted audio download without blocking on the download."""
        downloader = mock_factory.get_youtube_downloader.return_value
        downloader.validate_url.return_value = True
        downloader.extract_video_id.return_value = "dQw4w9WgXcQ"
        service.get_status = AsyncMock(
            return_value=YouTubeAuthStatus(
                mode=YouTubeAuthMode.MANAGED_COOKIE,
                encryption_configured=True,
                has_managed_cookie=True,
                source_label="browser",
                updated_at=datetime.now(UTC),
                runtime_file_present=True,
                cookie_line_count=10,
                domain_count=2,
                contains_youtube_domains=True,
                has_login_cookie_names=True,
            )
        )

        saved_download = await service.create_saved_audio_download(
            youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            preset=AudioDownloadPreset.MP3_192,
        )

        assert saved_download.state == AudioDownloadState.QUEUED
        assert saved_download.filename is None
        assert saved_download.youtube_id == "dQw4w9WgXcQ"
        mock_document_db.insert.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_process_saved_audio_download_completes_job(
        self,
        service,
        mock_document_db,
        mock_factory,
    ):
        """Run a queued job through downloading, uploading, and completion."""
        queued_document = SavedYouTubeAudioDownload(
            id="download-1",
            youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            youtube_id="dQw4w9WgXcQ",
            title=None,
            channel_name=None,
            duration_seconds=None,
            auth_mode=YouTubeAuthMode.MANAGED_COOKIE,
            preset=AudioDownloadPreset.MP3_128,
            audio_format="mp3",
            audio_quality="128",
            filename=None,
            file_size_bytes=None,
            bucket=None,
            blob_path=None,
            state=AudioDownloadState.QUEUED,
            state_message="Queued for authenticated audio download.",
        )
        mock_document_db.find_by_id.return_value = queued_document.model_dump(
            mode="json"
        )

        with TemporaryDirectory() as temp_dir:
            cleanup_dir = Path(temp_dir)
            artifact_path = cleanup_dir / "track.mp3"
            artifact_path.write_bytes(b"fake audio bytes")

            service.prepare_audio_download = AsyncMock(
                return_value=PreparedYouTubeAudioDownload(
                    youtube_url=queued_document.youtube_url,
                    youtube_id="dQw4w9WgXcQ",
                    title="Never Gonna Give You Up",
                    channel_name="Rick Astley",
                    duration_seconds=213,
                    auth_mode=YouTubeAuthMode.MANAGED_COOKIE,
                    audio_format="mp3",
                    audio_quality="128",
                    file_path=artifact_path,
                    cleanup_dir=cleanup_dir,
                )
            )

            await service.process_saved_audio_download(download_id="download-1")

        blob_storage = mock_factory.get_blob_storage.return_value
        blob_storage.upload.assert_awaited_once()
        assert mock_document_db.update.await_count == 3
        final_update = mock_document_db.update.await_args_list[-1].args[2]
        assert final_update["state"] == AudioDownloadState.COMPLETED
        assert final_update["bucket"] == "videos"
        assert final_update["filename"].endswith(".mp3")

    @pytest.mark.asyncio
    async def test_delete_saved_audio_download_rejects_active_job(
        self,
        service,
    ):
        """Active jobs cannot be deleted while they are still running."""
        service.get_saved_audio_download = AsyncMock(
            return_value=SavedYouTubeAudioDownload(
                id="download-1",
                youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                youtube_id="dQw4w9WgXcQ",
                title=None,
                channel_name=None,
                duration_seconds=None,
                auth_mode=YouTubeAuthMode.MANAGED_COOKIE,
                preset=AudioDownloadPreset.MP3_192,
                audio_format="mp3",
                audio_quality="192",
                filename=None,
                file_size_bytes=None,
                bucket=None,
                blob_path=None,
                state=AudioDownloadState.DOWNLOADING,
                state_message="Fetching audio from YouTube with current credentials.",
            )
        )

        with pytest.raises(AudioDownloadStateConflictError):
            await service.delete_saved_audio_download(download_id="download-1")
