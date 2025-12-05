"""Chunking configuration value object."""

from pydantic import BaseModel, Field


class ChunkingConfig(BaseModel):
    """Configuration for chunk generation.

    This value object encapsulates all parameters needed for
    splitting video content into chunks for processing and indexing.
    """

    transcript_chunk_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Duration of each transcript chunk in seconds",
    )
    transcript_overlap_seconds: int = Field(
        default=5,
        ge=0,
        le=30,
        description="Overlap between consecutive transcript chunks in seconds",
    )
    frame_interval_seconds: float = Field(
        default=2.0,
        ge=0.5,
        le=60,
        description="Interval between extracted frames in seconds",
    )
    audio_chunk_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Duration of each audio chunk in seconds",
    )
    video_chunk_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Duration of each video chunk for multimodal LLMs",
    )
    video_chunk_overlap_seconds: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Overlap between consecutive video chunks in seconds",
    )
    video_chunk_max_size_mb: float = Field(
        default=20.0,
        ge=1.0,
        le=100.0,
        description="Maximum size per video chunk in MB",
    )

    def calculate_transcript_chunks(self, duration_seconds: float) -> int:
        """Calculate the number of transcript chunks for a given duration.

        Args:
            duration_seconds: Total duration in seconds.

        Returns:
            Estimated number of chunks.
        """
        if duration_seconds <= 0:
            return 0
        step = self.transcript_chunk_seconds - self.transcript_overlap_seconds
        if step <= 0:
            return 1
        return max(1, int((duration_seconds - self.transcript_overlap_seconds) / step))

    def calculate_frame_count(self, duration_seconds: float) -> int:
        """Calculate the number of frames for a given duration.

        Args:
            duration_seconds: Total duration in seconds.

        Returns:
            Estimated number of frames.
        """
        if duration_seconds <= 0:
            return 0
        return max(1, int(duration_seconds / self.frame_interval_seconds))

    def calculate_video_chunks(self, duration_seconds: float) -> int:
        """Calculate the number of video chunks for a given duration.

        Args:
            duration_seconds: Total duration in seconds.

        Returns:
            Estimated number of video chunks.
        """
        if duration_seconds <= 0:
            return 0
        step = self.video_chunk_seconds - self.video_chunk_overlap_seconds
        if step <= 0:
            return 1
        return max(1, int((duration_seconds - self.video_chunk_overlap_seconds) / step))
