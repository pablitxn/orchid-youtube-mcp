"""Managed yt-dlp cookie storage for authenticated YouTube downloads."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from time import perf_counter
from typing import TYPE_CHECKING, ClassVar
from uuid import uuid4

from cryptography.fernet import Fernet, InvalidToken

from src.application.dtos.youtube_auth import (
    AudioDownloadPreset,
    AudioDownloadState,
    ManagedYouTubeCookie,
    PreparedYouTubeAudioDownload,
    SavedYouTubeAudioDownload,
    YouTubeAuthMode,
    YouTubeAuthStatus,
    YouTubeDownloadTestResult,
)
from src.infrastructure.telemetry import get_logger
from src.infrastructure.youtube.downloader import (
    DownloadError,
    VideoNotFoundError,
    YtDlpDownloader,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from src.infrastructure.adapters.document import DocumentStoreAdapter
    from src.infrastructure.factory import InfrastructureFactory
    from src.infrastructure.settings.models import Settings


@dataclass(frozen=True)
class _CookieSummary:
    line_count: int
    domain_count: int
    contains_youtube_domains: bool
    has_login_cookie_names: bool


@dataclass(frozen=True)
class _AudioDownloadPresetSpec:
    audio_format: str
    audio_quality: str


_AUDIO_DOWNLOAD_PRESETS: dict[AudioDownloadPreset, _AudioDownloadPresetSpec] = {
    AudioDownloadPreset.MP3_128: _AudioDownloadPresetSpec(
        audio_format="mp3",
        audio_quality="128",
    ),
    AudioDownloadPreset.MP3_192: _AudioDownloadPresetSpec(
        audio_format="mp3",
        audio_quality="192",
    ),
    AudioDownloadPreset.M4A_128: _AudioDownloadPresetSpec(
        audio_format="m4a",
        audio_quality="128",
    ),
    AudioDownloadPreset.OPUS_160: _AudioDownloadPresetSpec(
        audio_format="opus",
        audio_quality="160",
    ),
}
_AUDIO_DOWNLOAD_DOCUMENT_KIND = "saved_audio_download"
_AUDIO_DOWNLOAD_PREFIX = "audio-downloads"
_MAX_CONCURRENT_AUDIO_DOWNLOADS = 3
_ACTIVE_AUDIO_DOWNLOAD_STATES = frozenset(
    {
        AudioDownloadState.QUEUED,
        AudioDownloadState.DOWNLOADING,
        AudioDownloadState.UPLOADING,
    }
)
_INTERRUPTED_AUDIO_DOWNLOAD_ERROR_CODE = "AUDIO_DOWNLOAD_INTERRUPTED"


class AudioDownloadStateConflictError(Exception):
    """Raised when an audio download action conflicts with its current state."""

    def __init__(self, *, download_id: str, state: AudioDownloadState) -> None:
        self.download_id = download_id
        self.state = state
        super().__init__(
            f"Audio download '{download_id}' is still {state.value} and cannot "
            "be modified yet."
        )


class YouTubeAuthService:
    """Persist and materialize a managed cookies.txt for yt-dlp."""

    _COOKIE_DOCUMENT_ID = "youtube_auth_cookie"
    _active_download_tasks: ClassVar[set[asyncio.Task[None]]] = set()
    _download_semaphore: ClassVar[asyncio.Semaphore | None] = None

    def __init__(
        self,
        *,
        document_db: DocumentStoreAdapter,
        factory: InfrastructureFactory,
        settings: Settings,
    ) -> None:
        self._document_db = document_db
        self._factory = factory
        self._settings = settings
        self._collection = settings.document_db.collections.app_state
        self._runtime_file = Path(settings.youtube.managed_cookies_file)
        self._encryption_key = settings.youtube.managed_cookies_encryption_key
        self._downloads_bucket = settings.blob_storage.buckets.videos
        self._logger = get_logger(__name__)

    async def bootstrap_runtime_cookie_file(self) -> None:
        """Restore the managed cookie file into the pod filesystem on startup."""
        stored_cookie = await self._get_stored_cookie()
        if stored_cookie is None:
            self._remove_runtime_file()
            self._disable_auth()
            return

        decrypted_cookie = self._decrypt_cookie_text(
            stored_cookie.encrypted_cookie_text
        )
        if decrypted_cookie is None:
            self._remove_runtime_file()
            self._disable_auth()
            return

        self._write_runtime_file(decrypted_cookie)
        self._apply_managed_auth()

    async def get_status(self) -> YouTubeAuthStatus:
        """Return the current yt-dlp auth mode and managed cookie summary."""
        stored_cookie = await self._get_stored_cookie()
        runtime_file_present = self._runtime_file.exists()
        mode = (
            YouTubeAuthMode.MANAGED_COOKIE
            if stored_cookie is not None and runtime_file_present
            else YouTubeAuthMode.NONE
        )

        return YouTubeAuthStatus(
            mode=mode,
            encryption_configured=self._get_cipher() is not None,
            has_managed_cookie=stored_cookie is not None,
            source_label=stored_cookie.source_label if stored_cookie else None,
            updated_at=stored_cookie.updated_at if stored_cookie else None,
            runtime_file_present=runtime_file_present,
            cookie_line_count=stored_cookie.cookie_line_count if stored_cookie else 0,
            domain_count=stored_cookie.domain_count if stored_cookie else 0,
            contains_youtube_domains=(
                stored_cookie.contains_youtube_domains if stored_cookie else False
            ),
            has_login_cookie_names=(
                stored_cookie.has_login_cookie_names if stored_cookie else False
            ),
        )

    async def save_cookie(
        self,
        *,
        cookie_text: str,
        source_label: str | None = None,
    ) -> YouTubeAuthStatus:
        """Persist a managed cookies.txt and activate it immediately."""
        normalized_cookie = _normalize_cookie_text(cookie_text)
        summary = _summarize_cookie_text(normalized_cookie)
        encrypted_cookie = self._encrypt_cookie_text(normalized_cookie)

        stored_cookie = ManagedYouTubeCookie(
            id=self._COOKIE_DOCUMENT_ID,
            source_label=(source_label.strip() or None) if source_label else None,
            encrypted_cookie_text=encrypted_cookie,
            cookie_line_count=summary.line_count,
            domain_count=summary.domain_count,
            contains_youtube_domains=summary.contains_youtube_domains,
            has_login_cookie_names=summary.has_login_cookie_names,
        )

        existing = await self._document_db.find_by_id(
            self._collection,
            self._COOKIE_DOCUMENT_ID,
        )
        if existing is None:
            await self._document_db.insert(
                self._collection,
                stored_cookie.model_dump(mode="json"),
            )
        else:
            await self._document_db.update(
                self._collection,
                self._COOKIE_DOCUMENT_ID,
                stored_cookie.model_dump(mode="json"),
            )

        self._write_runtime_file(normalized_cookie)
        self._apply_managed_auth()
        return await self.get_status()

    async def clear_cookie(self) -> YouTubeAuthStatus:
        """Delete the managed cookies.txt and disable authenticated downloads."""
        await self._document_db.delete(self._collection, self._COOKIE_DOCUMENT_ID)
        self._remove_runtime_file()
        self._disable_auth()
        return await self.get_status()

    async def prepare_audio_download(
        self,
        *,
        youtube_url: str,
        preset: AudioDownloadPreset,
    ) -> PreparedYouTubeAudioDownload:
        """Download audio into a temporary directory for browser delivery."""
        downloader = self._factory.get_youtube_downloader()
        if not downloader.validate_url(youtube_url):
            raise ValueError(
                "Paste a supported YouTube watch, shorts, or youtu.be URL."
            )

        auth_status = await self.get_status()
        scratch_root = self._runtime_file.parent
        scratch_root.mkdir(parents=True, exist_ok=True)

        preset_spec = _AUDIO_DOWNLOAD_PRESETS[preset]
        temp_dir = Path(mkdtemp(prefix="browser-audio-", dir=scratch_root))

        try:
            artifact_path, metadata = await downloader.download_audio_only(
                youtube_url,
                temp_dir,
                audio_format=preset_spec.audio_format,
                audio_quality=preset_spec.audio_quality,
            )
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise

        return PreparedYouTubeAudioDownload(
            youtube_url=youtube_url,
            youtube_id=metadata.id,
            title=metadata.title,
            channel_name=metadata.channel_name,
            duration_seconds=metadata.duration_seconds,
            auth_mode=auth_status.mode,
            audio_format=preset_spec.audio_format,
            audio_quality=preset_spec.audio_quality,
            file_path=artifact_path,
            cleanup_dir=temp_dir,
        )

    async def create_saved_audio_download(
        self,
        *,
        youtube_url: str,
        preset: AudioDownloadPreset,
    ) -> SavedYouTubeAudioDownload:
        """Create a persisted audio download job and return its initial state."""
        downloader = self._factory.get_youtube_downloader()
        if not downloader.validate_url(youtube_url):
            raise ValueError(
                "Paste a supported YouTube watch, shorts, or youtu.be URL."
            )

        auth_status = await self.get_status()
        download_id = uuid4().hex
        queued_at = datetime.now(UTC)
        preset_spec = _AUDIO_DOWNLOAD_PRESETS[preset]
        saved_download = SavedYouTubeAudioDownload(
            id=download_id,
            kind=_AUDIO_DOWNLOAD_DOCUMENT_KIND,
            youtube_url=youtube_url,
            youtube_id=downloader.extract_video_id(youtube_url),
            title=None,
            channel_name=None,
            duration_seconds=None,
            auth_mode=auth_status.mode,
            preset=preset,
            audio_format=preset_spec.audio_format,
            audio_quality=preset_spec.audio_quality,
            filename=None,
            file_size_bytes=None,
            bucket=None,
            blob_path=None,
            state=AudioDownloadState.QUEUED,
            state_message="Queued for authenticated audio download.",
            created_at=queued_at,
            updated_at=queued_at,
        )

        await self._document_db.insert(
            self._collection,
            saved_download.model_dump(mode="json"),
        )
        self._logger.info(
            "Queued saved audio download",
            extra={
                "download_id": download_id,
                "youtube_url": youtube_url,
                "youtube_id": saved_download.youtube_id,
                "preset": preset.value,
                "auth_mode": auth_status.mode.value,
            },
        )
        return saved_download

    def schedule_saved_audio_download(self, *, download_id: str) -> None:
        """Schedule background processing for a persisted audio download job."""
        task = asyncio.create_task(
            self.process_saved_audio_download(download_id=download_id)
        )
        self._active_download_tasks.add(task)
        task.add_done_callback(self._forget_active_download_task)

    async def process_saved_audio_download(self, *, download_id: str) -> None:
        """Run the queued audio download job and persist lifecycle states."""
        saved_download = await self.get_saved_audio_download(download_id=download_id)
        if saved_download is None:
            self._logger.warning(
                "Skipping missing saved audio download job",
                extra={"download_id": download_id},
            )
            return

        if saved_download.state not in _ACTIVE_AUDIO_DOWNLOAD_STATES:
            self._logger.debug(
                "Skipping audio download job outside active states",
                extra={
                    "download_id": download_id,
                    "state": saved_download.state.value,
                },
            )
            return

        async with self._get_download_semaphore():
            prepared_download: PreparedYouTubeAudioDownload | None = None
            blob_path: str | None = None
            filename: str | None = None
            file_size_bytes: int | None = None
            blob_storage = self._factory.get_blob_storage()

            try:
                await self._set_saved_audio_download_state(
                    download_id=download_id,
                    state=AudioDownloadState.DOWNLOADING,
                    state_message=(
                        "Fetching audio from YouTube with current credentials."
                    ),
                    error_code=None,
                    error_message=None,
                )
                prepared_download = await self.prepare_audio_download(
                    youtube_url=saved_download.youtube_url,
                    preset=saved_download.preset,
                )
                filename = _build_audio_download_filename(
                    prepared_download.title,
                    prepared_download.youtube_id,
                    prepared_download.audio_format,
                )
                blob_path = (
                    f"{_AUDIO_DOWNLOAD_PREFIX}/{prepared_download.youtube_id}/"
                    f"{download_id}/{filename}"
                )
                file_size_bytes = (
                    prepared_download.file_path.stat().st_size
                    if prepared_download.file_path.exists()
                    else 0
                )

                await self._set_saved_audio_download_state(
                    download_id=download_id,
                    state=AudioDownloadState.UPLOADING,
                    state_message="Uploading artifact to MinIO.",
                    youtube_id=prepared_download.youtube_id,
                    title=prepared_download.title,
                    channel_name=prepared_download.channel_name,
                    duration_seconds=prepared_download.duration_seconds,
                    auth_mode=prepared_download.auth_mode,
                    filename=filename,
                    file_size_bytes=file_size_bytes,
                    error_code=None,
                    error_message=None,
                )

                with prepared_download.file_path.open("rb") as audio_file:
                    await blob_storage.upload(
                        self._downloads_bucket,
                        blob_path,
                        audio_file,
                        content_type=_audio_media_type(
                            prepared_download.audio_format
                        ),
                        metadata={
                            "youtube_id": prepared_download.youtube_id,
                            "preset": saved_download.preset.value,
                        },
                    )

                await self._set_saved_audio_download_state(
                    download_id=download_id,
                    state=AudioDownloadState.COMPLETED,
                    state_message="Saved to object storage and ready to download.",
                    youtube_id=prepared_download.youtube_id,
                    title=prepared_download.title,
                    channel_name=prepared_download.channel_name,
                    duration_seconds=prepared_download.duration_seconds,
                    auth_mode=prepared_download.auth_mode,
                    filename=filename,
                    file_size_bytes=file_size_bytes,
                    bucket=self._downloads_bucket,
                    blob_path=blob_path,
                    error_code=None,
                    error_message=None,
                )
            except Exception as exc:
                if blob_path is not None and await blob_storage.exists(
                    self._downloads_bucket, blob_path
                ):
                    await blob_storage.delete(self._downloads_bucket, blob_path)

                error_code, error_message = _audio_download_failure_details(exc)
                await self._set_saved_audio_download_state(
                    download_id=download_id,
                    state=AudioDownloadState.FAILED,
                    state_message="Audio download failed.",
                    youtube_id=(
                        prepared_download.youtube_id
                        if prepared_download is not None
                        else None
                    ),
                    title=(
                        prepared_download.title
                        if prepared_download is not None
                        else None
                    ),
                    channel_name=(
                        prepared_download.channel_name
                        if prepared_download is not None
                        else None
                    ),
                    duration_seconds=(
                        prepared_download.duration_seconds
                        if prepared_download is not None
                        else None
                    ),
                    auth_mode=(
                        prepared_download.auth_mode
                        if prepared_download is not None
                        else None
                    ),
                    filename=filename,
                    file_size_bytes=file_size_bytes,
                    error_code=error_code,
                    error_message=error_message,
                )
                self._logger.warning(
                    "Saved audio download failed",
                    extra={
                        "download_id": download_id,
                        "youtube_url": saved_download.youtube_url,
                        "youtube_id": saved_download.youtube_id,
                        "preset": saved_download.preset.value,
                        "error_code": error_code,
                    },
                    exc_info=not isinstance(
                        exc,
                        (DownloadError, VideoNotFoundError, ValueError),
                    ),
                )
            finally:
                if prepared_download is not None:
                    shutil.rmtree(prepared_download.cleanup_dir, ignore_errors=True)

    async def list_saved_audio_downloads(
        self,
        *,
        limit: int = 200,
    ) -> list[SavedYouTubeAudioDownload]:
        """List persisted audio-only downloads newest first."""
        documents = await self._document_db.find(
            self._collection,
            {"kind": _AUDIO_DOWNLOAD_DOCUMENT_KIND},
            skip=0,
            limit=limit,
            sort=[("created_at", -1)],
        )
        return [SavedYouTubeAudioDownload(**document) for document in documents]

    async def get_saved_audio_download(
        self,
        *,
        download_id: str,
    ) -> SavedYouTubeAudioDownload | None:
        """Fetch a persisted audio-only download by ID."""
        document = await self._document_db.find_by_id(self._collection, download_id)
        if document is None or document.get("kind") != _AUDIO_DOWNLOAD_DOCUMENT_KIND:
            return None
        return SavedYouTubeAudioDownload(**document)

    async def open_saved_audio_download(
        self,
        *,
        download_id: str,
    ) -> tuple[SavedYouTubeAudioDownload, AsyncIterator[bytes]] | None:
        """Resolve a saved download and its blob stream for browser delivery."""
        saved_download = await self.get_saved_audio_download(download_id=download_id)
        if saved_download is None:
            return None
        if (
            saved_download.state != AudioDownloadState.COMPLETED
            or saved_download.bucket is None
            or saved_download.blob_path is None
        ):
            return None

        blob_storage = self._factory.get_blob_storage()
        if not await blob_storage.exists(
            saved_download.bucket,
            saved_download.blob_path,
        ):
            return None

        return (
            saved_download,
            blob_storage.download_stream(
                saved_download.bucket,
                saved_download.blob_path,
            ),
        )

    async def delete_saved_audio_download(
        self,
        *,
        download_id: str,
    ) -> bool:
        """Delete a persisted audio-only download from storage and app_state."""
        saved_download = await self.get_saved_audio_download(download_id=download_id)
        if saved_download is None:
            return False
        if saved_download.state in _ACTIVE_AUDIO_DOWNLOAD_STATES:
            raise AudioDownloadStateConflictError(
                download_id=download_id,
                state=saved_download.state,
            )

        blob_storage = self._factory.get_blob_storage()
        if (
            saved_download.bucket is not None
            and saved_download.blob_path is not None
            and await blob_storage.exists(
                saved_download.bucket,
                saved_download.blob_path,
            )
        ):
            await blob_storage.delete(saved_download.bucket, saved_download.blob_path)

        return await self._document_db.delete(self._collection, download_id)

    async def recover_interrupted_audio_downloads(self) -> int:
        """Mark in-flight audio downloads as failed after an application restart."""
        now = datetime.now(UTC)
        recovered = await self._document_db.update_many(
            self._collection,
            {
                "kind": _AUDIO_DOWNLOAD_DOCUMENT_KIND,
                "state": {
                    "$in": [state.value for state in _ACTIVE_AUDIO_DOWNLOAD_STATES]
                },
            },
            {
                "state": AudioDownloadState.FAILED.value,
                "state_message": "Marked failed after application restart.",
                "error_code": _INTERRUPTED_AUDIO_DOWNLOAD_ERROR_CODE,
                "error_message": (
                    "The application restarted before the audio download finished."
                ),
                "updated_at": now,
                "completed_at": now,
            },
        )
        if recovered > 0:
            self._logger.warning(
                "Recovered interrupted audio download jobs",
                extra={"recovered_jobs": recovered},
            )
        return recovered

    async def test_download(self, *, youtube_url: str) -> YouTubeDownloadTestResult:
        """Run an ephemeral audio-only download to verify yt-dlp access."""
        started_at = perf_counter()
        prepared_download = await self.prepare_audio_download(
            youtube_url=youtube_url,
            preset=AudioDownloadPreset.MP3_128,
        )

        try:
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            downloaded_bytes = (
                prepared_download.file_path.stat().st_size
                if prepared_download.file_path.exists()
                else 0
            )
            return YouTubeDownloadTestResult(
                youtube_url=youtube_url,
                youtube_id=prepared_download.youtube_id,
                title=prepared_download.title,
                channel_name=prepared_download.channel_name,
                duration_seconds=prepared_download.duration_seconds,
                auth_mode=prepared_download.auth_mode,
                downloaded_bytes=downloaded_bytes,
                artifact_name=prepared_download.file_path.name,
                elapsed_ms=elapsed_ms,
                note=(
                    "Audio-only media was fetched to a temporary directory and "
                    "deleted immediately after verification."
                ),
            )
        finally:
            shutil.rmtree(prepared_download.cleanup_dir, ignore_errors=True)

    async def _get_stored_cookie(self) -> ManagedYouTubeCookie | None:
        document = await self._document_db.find_by_id(
            self._collection,
            self._COOKIE_DOCUMENT_ID,
        )
        if document is None:
            return None
        return ManagedYouTubeCookie(**document)

    def _write_runtime_file(self, cookie_text: str) -> None:
        self._runtime_file.parent.mkdir(parents=True, exist_ok=True)
        self._runtime_file.write_text(cookie_text, encoding="utf-8")
        self._runtime_file.chmod(0o600)

    def _remove_runtime_file(self) -> None:
        self._runtime_file.unlink(missing_ok=True)

    def _apply_managed_auth(self) -> None:
        downloader = self._factory.get_youtube_downloader()
        if not isinstance(downloader, YtDlpDownloader):
            return
        downloader.configure_auth(cookies_file=self._runtime_file)

    async def _set_saved_audio_download_state(
        self,
        *,
        download_id: str,
        state: AudioDownloadState,
        state_message: str | None,
        youtube_id: str | None = None,
        title: str | None = None,
        channel_name: str | None = None,
        duration_seconds: int | None = None,
        auth_mode: YouTubeAuthMode | None = None,
        filename: str | None = None,
        file_size_bytes: int | None = None,
        bucket: str | None = None,
        blob_path: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """Persist a lifecycle transition for a saved audio download job."""
        updated_at = datetime.now(UTC)
        updates: dict[str, object | None] = {
            "state": state,
            "state_message": state_message,
            "updated_at": updated_at,
            "error_code": error_code,
            "error_message": error_message,
        }
        if state in (AudioDownloadState.COMPLETED, AudioDownloadState.FAILED):
            updates["completed_at"] = updated_at

        for field, value in (
            ("youtube_id", youtube_id),
            ("title", title),
            ("channel_name", channel_name),
            ("duration_seconds", duration_seconds),
            ("auth_mode", auth_mode),
            ("filename", filename),
            ("file_size_bytes", file_size_bytes),
            ("bucket", bucket),
            ("blob_path", blob_path),
        ):
            if value is not None:
                updates[field] = value

        updated = await self._document_db.update(
            self._collection,
            download_id,
            updates,
        )
        if not updated:
            self._logger.warning(
                "Failed to persist audio download state transition",
                extra={
                    "download_id": download_id,
                    "state": state.value,
                },
            )
            return

        self._logger.info(
            "Audio download state changed",
            extra={
                "download_id": download_id,
                "state": state.value,
                "error_code": error_code,
            },
        )

    @classmethod
    def _forget_active_download_task(cls, task: asyncio.Task[None]) -> None:
        """Drop completed background tasks from the in-memory registry."""
        cls._active_download_tasks.discard(task)

    @classmethod
    def _get_download_semaphore(cls) -> asyncio.Semaphore:
        """Create the shared download limiter lazily for the process."""
        if cls._download_semaphore is None:
            cls._download_semaphore = asyncio.Semaphore(
                _MAX_CONCURRENT_AUDIO_DOWNLOADS
            )
        return cls._download_semaphore

    def _disable_auth(self) -> None:
        downloader = self._factory.get_youtube_downloader()
        if not isinstance(downloader, YtDlpDownloader):
            return
        downloader.configure_auth(cookies_file=None)

    def _get_cipher(self) -> Fernet | None:
        if not self._encryption_key:
            return None

        try:
            return Fernet(self._encryption_key.encode("utf-8"))
        except (TypeError, ValueError):
            return None

    def _encrypt_cookie_text(self, cookie_text: str) -> str:
        cipher = self._get_cipher()
        if cipher is None:
            raise RuntimeError(
                "Managed cookie encryption key is not configured correctly."
            )
        return cipher.encrypt(cookie_text.encode("utf-8")).decode("utf-8")

    def _decrypt_cookie_text(self, encrypted_cookie_text: str) -> str | None:
        cipher = self._get_cipher()
        if cipher is None:
            return None

        try:
            return cipher.decrypt(encrypted_cookie_text.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None


def _build_audio_download_filename(
    title: str,
    youtube_id: str,
    audio_format: str,
) -> str:
    """Create a predictable filename for stored audio downloads."""
    import re

    slug = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    stem = slug[:80] or youtube_id
    return f"{stem}-{youtube_id}.{audio_format}"


def _audio_media_type(audio_format: str) -> str:
    """Map response media types for the supported audio presets."""
    if audio_format == "m4a":
        return "audio/mp4"
    if audio_format == "opus":
        return "audio/ogg"
    return "audio/mpeg"


def _audio_download_failure_details(exc: Exception) -> tuple[str, str]:
    """Map background job failures to persisted operator-facing details."""
    if isinstance(exc, DownloadError):
        return exc.code, str(exc)
    if isinstance(exc, VideoNotFoundError):
        return "YOUTUBE_VIDEO_NOT_FOUND", str(exc)
    if isinstance(exc, ValueError):
        return "INVALID_YOUTUBE_URL", str(exc)

    message = str(exc).strip() or "The audio download job failed unexpectedly."
    return "AUDIO_DOWNLOAD_FAILED", message


def _normalize_cookie_text(value: str) -> str:
    """Normalize line endings and ensure the cookie is not empty."""
    normalized = value.replace("\r\n", "\n").strip()
    if not normalized:
        raise ValueError("Paste a non-empty cookies.txt export.")
    return f"{normalized}\n"


def _summarize_cookie_text(cookie_text: str) -> _CookieSummary:
    """Validate a Netscape cookies.txt payload and extract lightweight stats."""
    domains: set[str] = set()
    cookie_names: set[str] = set()
    line_count = 0

    for raw_line in cookie_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue

        fields = line.split("\t")
        if len(fields) < 7:
            continue

        domain = fields[0].removeprefix("#HttpOnly_").lstrip(".").lower()
        cookie_name = fields[5].strip()

        if not domain or not cookie_name:
            continue

        domains.add(domain)
        cookie_names.add(cookie_name)
        line_count += 1

    if line_count == 0:
        raise ValueError(
            "That does not look like a Netscape cookies.txt export from a browser."
        )

    contains_youtube_domains = any(
        "youtube.com" in domain or "google.com" in domain for domain in domains
    )
    has_login_cookie_names = any(
        cookie_name
        in {
            "LOGIN_INFO",
            "SID",
            "HSID",
            "SSID",
            "SAPISID",
            "__Secure-1PSID",
            "__Secure-3PSID",
        }
        for cookie_name in cookie_names
    )

    return _CookieSummary(
        line_count=line_count,
        domain_count=len(domains),
        contains_youtube_domains=contains_youtube_domains,
        has_login_cookie_names=has_login_cookie_names,
    )
