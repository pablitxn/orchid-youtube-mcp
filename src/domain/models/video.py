"""Video metadata domain model."""

from datetime import UTC, datetime
from enum import Enum
from typing import Self
from uuid import uuid4

from pydantic import BaseModel, Field


class VideoStatus(str, Enum):
    """Lifecycle status of a video in the system."""

    PENDING = "pending"  # Queued for processing
    DOWNLOADING = "downloading"  # Currently downloading from YouTube
    TRANSCRIBING = "transcribing"  # Extracting transcript
    EXTRACTING = "extracting"  # Extracting frames/audio
    EMBEDDING = "embedding"  # Generating embeddings
    READY = "ready"  # Fully processed and queryable
    FAILED = "failed"  # Processing failed


class VideoMetadata(BaseModel):
    """Core entity representing an indexed YouTube video.

    This is the aggregate root for video-related operations.
    All chunks and embeddings are associated with a video through video_id.
    """

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Internal UUID for this video record",
    )
    youtube_id: str = Field(description="YouTube video ID (11 characters)")
    youtube_url: str = Field(description="Full YouTube URL")
    title: str = Field(description="Video title from YouTube")
    description: str = Field(default="", description="Video description from YouTube")
    duration_seconds: int = Field(
        ge=0,
        description="Total video duration in seconds",
    )
    channel_name: str = Field(description="Name of the YouTube channel")
    channel_id: str = Field(description="YouTube channel ID")
    upload_date: datetime = Field(description="When the video was uploaded to YouTube")
    thumbnail_url: str = Field(description="URL to video thumbnail")
    language: str | None = Field(
        default=None,
        description="Detected/specified primary language (ISO 639-1)",
    )
    status: VideoStatus = Field(
        default=VideoStatus.PENDING,
        description="Current processing status",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this record was created in our system",
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Last update timestamp",
    )
    error_message: str | None = Field(
        default=None,
        description="Error details if status is FAILED",
    )

    # Processing metadata - paths in blob storage
    blob_path_video: str | None = Field(
        default=None,
        description="Path to video file in blob storage",
    )
    blob_path_audio: str | None = Field(
        default=None,
        description="Path to audio file in blob storage",
    )
    blob_path_metadata: str | None = Field(
        default=None,
        description="Path to metadata JSON in blob storage",
    )

    # Statistics (populated after processing)
    transcript_chunk_count: int = Field(
        default=0,
        ge=0,
        description="Number of transcript chunks created",
    )
    frame_chunk_count: int = Field(
        default=0,
        ge=0,
        description="Number of frame chunks created",
    )
    audio_chunk_count: int = Field(
        default=0,
        ge=0,
        description="Number of audio chunks created",
    )
    video_chunk_count: int = Field(
        default=0,
        ge=0,
        description="Number of video chunks created",
    )

    @property
    def is_ready(self) -> bool:
        """Check if video is ready for querying."""
        return self.status == VideoStatus.READY

    @property
    def is_failed(self) -> bool:
        """Check if video processing has failed."""
        return self.status == VideoStatus.FAILED

    @property
    def is_processing(self) -> bool:
        """Check if video is currently being processed."""
        return self.status in {
            VideoStatus.DOWNLOADING,
            VideoStatus.TRANSCRIBING,
            VideoStatus.EXTRACTING,
            VideoStatus.EMBEDDING,
        }

    @property
    def total_chunk_count(self) -> int:
        """Get total number of chunks across all modalities."""
        return (
            self.transcript_chunk_count
            + self.frame_chunk_count
            + self.audio_chunk_count
            + self.video_chunk_count
        )

    @property
    def duration_formatted(self) -> str:
        """Get duration as HH:MM:SS string."""
        hours, remainder = divmod(self.duration_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours:d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:d}:{seconds:02d}"

    def transition_to(self, new_status: VideoStatus) -> Self:
        """Create a new instance with updated status.

        Args:
            new_status: The new status to transition to.

        Returns:
            A new VideoMetadata instance with updated status and timestamp.
        """
        error_msg = self.error_message if new_status == VideoStatus.FAILED else None
        return self.model_copy(
            update={
                "status": new_status,
                "updated_at": datetime.now(UTC),
                "error_message": error_msg,
            }
        )

    def mark_failed(self, error_message: str) -> Self:
        """Create a new instance marked as failed with error message.

        Args:
            error_message: Description of what went wrong.

        Returns:
            A new VideoMetadata instance with FAILED status.
        """
        return self.model_copy(
            update={
                "status": VideoStatus.FAILED,
                "updated_at": datetime.now(UTC),
                "error_message": error_message,
            }
        )

    def update_chunk_counts(
        self,
        *,
        transcript: int | None = None,
        frame: int | None = None,
        audio: int | None = None,
        video: int | None = None,
    ) -> Self:
        """Create a new instance with updated chunk counts.

        Args:
            transcript: New transcript chunk count.
            frame: New frame chunk count.
            audio: New audio chunk count.
            video: New video chunk count.

        Returns:
            A new VideoMetadata instance with updated counts.
        """
        updates: dict[str, int | datetime] = {"updated_at": datetime.now(UTC)}
        if transcript is not None:
            updates["transcript_chunk_count"] = transcript
        if frame is not None:
            updates["frame_chunk_count"] = frame
        if audio is not None:
            updates["audio_chunk_count"] = audio
        if video is not None:
            updates["video_chunk_count"] = video
        return self.model_copy(update=updates)
