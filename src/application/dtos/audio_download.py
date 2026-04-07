"""DTOs for batch audio download operations."""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from datetime import datetime


class AudioDownloadItemStatus(str, Enum):
    """Lifecycle for an item within an audio download batch."""

    QUEUED = "queued"
    DOWNLOADING = "downloading"
    COMPLETED = "completed"
    FAILED = "failed"


class AudioDownloadBatchStatus(str, Enum):
    """Lifecycle for an audio download batch job."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    COMPLETED_WITH_ERRORS = "completed_with_errors"


class AudioDownloadBatchRequest(BaseModel):
    """Request payload for an audio-only batch download job."""

    youtube_urls: list[str] = Field(
        min_length=1,
        description="One or more YouTube URLs to download as audio",
    )
    output_dir: str | None = Field(
        default=None,
        description=(
            "Optional target directory. The server creates a per-job subdirectory "
            "inside this path."
        ),
    )
    audio_format: str = Field(
        default="mp3",
        description="Target audio format supported by yt-dlp/FFmpeg",
    )
    audio_quality: str = Field(
        default="192",
        description="Preferred bitrate in kbps",
    )
    max_concurrent_downloads: int = Field(
        default=3,
        ge=1,
        le=3,
        description="Maximum simultaneous downloads. Hard-capped at 3.",
    )

    @model_validator(mode="after")
    def normalize_urls(self) -> AudioDownloadBatchRequest:
        """Strip URLs and reject empty inputs after normalization."""
        normalized = [url.strip() for url in self.youtube_urls if url.strip()]
        if not normalized:
            raise ValueError("youtube_urls must contain at least one non-empty URL")
        self.youtube_urls = normalized
        return self


class AudioDownloadItemResponse(BaseModel):
    """Per-item status inside a batch."""

    index: int = Field(description="Original position within the submitted list")
    youtube_url: str = Field(description="Requested YouTube URL")
    status: AudioDownloadItemStatus = Field(description="Current item status")
    youtube_id: str | None = Field(
        default=None,
        description="Resolved YouTube video ID when available",
    )
    title: str | None = Field(default=None, description="Resolved video title")
    output_path: str | None = Field(
        default=None,
        description="Absolute local path of the downloaded audio file",
    )
    error_message: str | None = Field(
        default=None,
        description="Failure details for errored items",
    )
    started_at: datetime | None = Field(
        default=None,
        description="When the item actually started downloading",
    )
    completed_at: datetime | None = Field(
        default=None,
        description="When the item finished or failed",
    )


class AudioDownloadBatchResponse(BaseModel):
    """Status snapshot for an audio download batch job."""

    job_id: str = Field(description="Batch job identifier")
    status: AudioDownloadBatchStatus = Field(description="Current batch status")
    total_items: int = Field(description="Total submitted URLs")
    queued_items: int = Field(description="Items waiting for execution")
    active_items: int = Field(description="Items currently downloading")
    completed_items: int = Field(description="Successfully downloaded items")
    failed_items: int = Field(description="Items that failed")
    output_dir: str = Field(
        description="Absolute output directory dedicated to this batch",
    )
    audio_format: str = Field(description="Target audio format")
    audio_quality: str = Field(description="Target audio bitrate in kbps")
    max_concurrent_downloads: int = Field(
        description="Effective concurrency limit applied to this batch",
    )
    created_at: datetime = Field(description="When the batch was submitted")
    finished_at: datetime | None = Field(
        default=None,
        description="When the batch finished processing",
    )
    items: list[AudioDownloadItemResponse] = Field(
        default_factory=list,
        description="Per-item progress and results",
    )


def _rebuild_models() -> None:
    """Resolve deferred datetime annotations for Pydantic."""
    from datetime import datetime

    AudioDownloadItemResponse.model_rebuild(_types_namespace={"datetime": datetime})
    AudioDownloadBatchResponse.model_rebuild(_types_namespace={"datetime": datetime})


_rebuild_models()
