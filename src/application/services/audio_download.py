"""Background batch audio download service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from src.application.dtos.audio_download import (
    AudioDownloadBatchRequest,
    AudioDownloadBatchResponse,
    AudioDownloadBatchStatus,
    AudioDownloadItemResponse,
    AudioDownloadItemStatus,
)
from src.infrastructure.telemetry import get_logger

_DEFAULT_AUDIO_OUTPUT_DIR = Path.cwd() / "data" / "audio-downloads"
_audio_download_service_state: dict[str, AudioDownloadBatchService | None] = {
    "instance": None,
}

if TYPE_CHECKING:
    from src.infrastructure.youtube.base import YouTubeDownloaderBase


class AudioDownloadBatchService:
    """Schedules audio-only downloads with bounded concurrency."""

    def __init__(
        self,
        youtube_downloader: YouTubeDownloaderBase,
        default_output_dir: Path | None = None,
    ) -> None:
        self._downloader = youtube_downloader
        self._default_output_dir = (
            default_output_dir or _DEFAULT_AUDIO_OUTPUT_DIR
        ).expanduser()
        self._jobs: dict[str, AudioDownloadBatchResponse] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._state_lock = asyncio.Lock()
        self._logger = get_logger(__name__)

    async def submit_batch(
        self,
        request: AudioDownloadBatchRequest,
    ) -> AudioDownloadBatchResponse:
        """Create a background batch job and return the initial snapshot."""
        job_id = uuid4().hex
        root_output_dir = (
            Path(request.output_dir).expanduser()
            if request.output_dir
            else self._default_output_dir
        )
        batch_output_dir = (root_output_dir / job_id).resolve()
        batch_output_dir.mkdir(parents=True, exist_ok=True)

        job = AudioDownloadBatchResponse(
            job_id=job_id,
            status=AudioDownloadBatchStatus.QUEUED,
            total_items=len(request.youtube_urls),
            queued_items=len(request.youtube_urls),
            active_items=0,
            completed_items=0,
            failed_items=0,
            output_dir=str(batch_output_dir),
            audio_format=request.audio_format,
            audio_quality=request.audio_quality,
            max_concurrent_downloads=min(3, request.max_concurrent_downloads),
            created_at=datetime.now(UTC),
            items=[
                AudioDownloadItemResponse(
                    index=index,
                    youtube_url=url,
                    status=AudioDownloadItemStatus.QUEUED,
                )
                for index, url in enumerate(request.youtube_urls)
            ],
        )

        async with self._state_lock:
            self._jobs[job_id] = job

        task = asyncio.create_task(
            self._run_batch(job_id),
            name=f"audio-batch-{job_id}",
        )
        task.add_done_callback(self._make_done_callback(job_id))
        self._tasks[job_id] = task

        self._logger.info(
            "Audio download batch submitted",
            extra={
                "job_id": job_id,
                "total_items": job.total_items,
                "output_dir": job.output_dir,
                "max_concurrent_downloads": job.max_concurrent_downloads,
            },
        )

        return await self.get_batch(job_id) or job.model_copy(deep=True)

    def _make_done_callback(self, job_id: str):
        """Build a completion callback bound to a specific batch ID."""

        def callback(_task: asyncio.Task[None]) -> None:
            self._tasks.pop(job_id, None)

        return callback

    async def get_batch(self, job_id: str) -> AudioDownloadBatchResponse | None:
        """Return a deep copy of the current batch state."""
        async with self._state_lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            return job.model_copy(deep=True)

    async def shutdown(self) -> None:
        """Cancel running jobs and clear in-memory state."""
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        async with self._state_lock:
            self._tasks.clear()
            self._jobs.clear()

    async def _run_batch(self, job_id: str) -> None:
        """Execute the batch with bounded concurrency."""
        job = await self.get_batch(job_id)
        if job is None:
            return

        await self._update_batch_status(job_id, AudioDownloadBatchStatus.RUNNING)
        semaphore = asyncio.Semaphore(job.max_concurrent_downloads)

        async def worker(index: int) -> None:
            current_job = await self.get_batch(job_id)
            if current_job is None:
                return
            item = current_job.items[index]

            if not self._downloader.validate_url(item.youtube_url):
                await self._set_item_failed(
                    job_id=job_id,
                    index=index,
                    message="Invalid YouTube URL",
                )
                return

            async with semaphore:
                await self._set_item_downloading(job_id=job_id, index=index)
                try:
                    output_path, metadata = await self._downloader.download_audio_only(
                        url=item.youtube_url,
                        output_dir=Path(current_job.output_dir),
                        audio_format=current_job.audio_format,
                        audio_quality=current_job.audio_quality,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    await self._set_item_failed(
                        job_id=job_id,
                        index=index,
                        message=str(exc),
                    )
                    return

                await self._set_item_completed(
                    job_id=job_id,
                    index=index,
                    youtube_id=metadata.id,
                    title=metadata.title,
                    output_path=str(output_path.resolve()),
                )

        try:
            await asyncio.gather(
                *(worker(index) for index in range(job.total_items)),
            )
        except asyncio.CancelledError:
            self._logger.warning(
                "Audio download batch cancelled",
                extra={"job_id": job_id},
            )
            raise
        except Exception:
            self._logger.exception(
                "Unexpected failure while executing audio batch",
                extra={"job_id": job_id},
            )
        finally:
            await self._finalize_batch(job_id)

    async def _update_batch_status(
        self,
        job_id: str,
        status: AudioDownloadBatchStatus,
    ) -> None:
        async with self._state_lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = status

    async def _set_item_downloading(self, job_id: str, index: int) -> None:
        async with self._state_lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            item = job.items[index]
            item.status = AudioDownloadItemStatus.DOWNLOADING
            item.started_at = datetime.now(UTC)
            self._refresh_counts(job)

    async def _set_item_completed(
        self,
        job_id: str,
        index: int,
        youtube_id: str,
        title: str,
        output_path: str,
    ) -> None:
        async with self._state_lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            item = job.items[index]
            item.status = AudioDownloadItemStatus.COMPLETED
            item.youtube_id = youtube_id
            item.title = title
            item.output_path = output_path
            item.completed_at = datetime.now(UTC)
            self._refresh_counts(job)

    async def _set_item_failed(
        self,
        job_id: str,
        index: int,
        message: str,
    ) -> None:
        async with self._state_lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            item = job.items[index]
            item.status = AudioDownloadItemStatus.FAILED
            item.error_message = message
            item.completed_at = datetime.now(UTC)
            self._refresh_counts(job)

    async def _finalize_batch(self, job_id: str) -> None:
        async with self._state_lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            self._refresh_counts(job)
            job.finished_at = datetime.now(UTC)
            if job.failed_items > 0:
                job.status = AudioDownloadBatchStatus.COMPLETED_WITH_ERRORS
            else:
                job.status = AudioDownloadBatchStatus.COMPLETED

    def _refresh_counts(self, job: AudioDownloadBatchResponse) -> None:
        job.queued_items = sum(
            item.status == AudioDownloadItemStatus.QUEUED for item in job.items
        )
        job.active_items = sum(
            item.status == AudioDownloadItemStatus.DOWNLOADING for item in job.items
        )
        job.completed_items = sum(
            item.status == AudioDownloadItemStatus.COMPLETED for item in job.items
        )
        job.failed_items = sum(
            item.status == AudioDownloadItemStatus.FAILED for item in job.items
        )


def get_audio_download_service_instance(
    youtube_downloader: YouTubeDownloaderBase | None = None,
) -> AudioDownloadBatchService:
    """Return the shared audio download service instance."""
    if _audio_download_service_state["instance"] is None:
        if youtube_downloader is None:
            raise ValueError("youtube_downloader is required to initialize the service")
        _audio_download_service_state["instance"] = AudioDownloadBatchService(
            youtube_downloader=youtube_downloader,
        )
    instance = _audio_download_service_state["instance"]
    if instance is None:
        raise RuntimeError("audio download service failed to initialize")
    return instance


async def shutdown_audio_download_service_instance() -> None:
    """Shutdown and clear the shared audio download service instance."""
    instance = _audio_download_service_state["instance"]
    if instance is None:
        return
    await instance.shutdown()
    _audio_download_service_state["instance"] = None
