"""DTOs for video ingestion operations."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ProcessingStep(str, Enum):
    """Individual steps in the ingestion pipeline."""

    VALIDATING = "validating"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    EXTRACTING_FRAMES = "extracting_frames"
    EXTRACTING_AUDIO = "extracting_audio"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    STORING = "storing"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestionStatus(str, Enum):
    """Overall ingestion status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class IngestVideoRequest(BaseModel):
    """Request to ingest a YouTube video."""

    url: str = Field(description="YouTube video URL to ingest")
    language_hint: str | None = Field(
        default=None,
        description="ISO language code hint for transcription (e.g., 'en', 'es')",
    )
    extract_frames: bool = Field(
        default=True,
        description="Whether to extract video frames for visual analysis",
    )
    extract_audio_chunks: bool = Field(
        default=False,
        description="Whether to create separate audio chunks",
    )
    extract_video_chunks: bool = Field(
        default=False,
        description="Whether to create video segment chunks for multimodal analysis",
    )
    max_resolution: int = Field(
        default=720,
        ge=144,
        le=2160,
        description="Maximum video resolution to download",
    )


class IngestionProgress(BaseModel):
    """Progress information for an ongoing ingestion."""

    current_step: ProcessingStep = Field(description="Current processing step")
    step_progress: float = Field(
        ge=0.0,
        le=1.0,
        description="Progress within current step (0.0 to 1.0)",
    )
    overall_progress: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall ingestion progress (0.0 to 1.0)",
    )
    message: str = Field(description="Human-readable progress message")
    started_at: datetime = Field(description="When ingestion started")
    estimated_remaining_seconds: int | None = Field(
        default=None,
        description="Estimated seconds remaining",
    )


class IngestVideoResponse(BaseModel):
    """Response from video ingestion."""

    video_id: str = Field(description="Internal UUID for the ingested video")
    youtube_id: str = Field(description="YouTube video ID")
    title: str = Field(description="Video title")
    duration_seconds: int = Field(description="Video duration in seconds")
    status: IngestionStatus = Field(description="Current ingestion status")
    progress: IngestionProgress | None = Field(
        default=None,
        description="Progress details if still processing",
    )
    error_message: str | None = Field(
        default=None,
        description="Error details if failed",
    )
    chunk_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Number of chunks created by modality",
    )
    created_at: datetime = Field(description="When ingestion was initiated")
