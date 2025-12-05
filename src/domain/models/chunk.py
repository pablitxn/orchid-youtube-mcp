"""Chunk domain models for different content modalities."""

from abc import ABC
from datetime import UTC, datetime
from enum import Enum
from typing import Self
from uuid import uuid4

from pydantic import BaseModel, Field


class Modality(str, Enum):
    """Content modality type."""

    TRANSCRIPT = "transcript"
    FRAME = "frame"
    AUDIO = "audio"
    VIDEO = "video"


class BaseChunk(BaseModel, ABC):
    """Abstract base class for all chunk types.

    Chunks represent temporally-positioned segments of video content
    that can be independently embedded and retrieved.
    """

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique chunk identifier",
    )
    video_id: str = Field(description="Reference to parent VideoMetadata")
    modality: Modality = Field(description="Type of content this chunk represents")
    start_time: float = Field(
        ge=0,
        description="Start time in seconds from video beginning",
    )
    end_time: float = Field(
        ge=0,
        description="End time in seconds from video beginning",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this chunk was created",
    )

    @property
    def duration_seconds(self) -> float:
        """Calculate chunk duration."""
        return self.end_time - self.start_time

    def overlaps_with(self, other: "BaseChunk") -> bool:
        """Check if this chunk overlaps temporally with another.

        Args:
            other: Another chunk to compare with.

        Returns:
            True if the chunks overlap in time.
        """
        return not (
            self.end_time <= other.start_time or self.start_time >= other.end_time
        )

    def contains_timestamp(self, timestamp: float) -> bool:
        """Check if a timestamp falls within this chunk.

        Args:
            timestamp: Time in seconds to check.

        Returns:
            True if the timestamp is within this chunk.
        """
        return self.start_time <= timestamp < self.end_time

    def format_time_range(self) -> str:
        """Format time range as MM:SS - MM:SS for display."""

        def fmt(seconds: float) -> str:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes:02d}:{secs:02d}"

        return f"{fmt(self.start_time)} - {fmt(self.end_time)}"


class WordTimestamp(BaseModel):
    """Individual word with precise timing."""

    word: str = Field(description="The spoken word")
    start_time: float = Field(ge=0, description="Word start time in seconds")
    end_time: float = Field(ge=0, description="Word end time in seconds")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Transcription confidence score",
    )


class TranscriptChunk(BaseChunk):
    """A segment of transcribed speech.

    Contains the text content along with word-level timestamps
    for precise citation and navigation.
    """

    modality: Modality = Field(default=Modality.TRANSCRIPT, frozen=True)
    text: str = Field(description="Transcribed text content")
    language: str = Field(description="Detected language (ISO 639-1)")
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall transcription confidence",
    )
    word_timestamps: list[WordTimestamp] = Field(
        default_factory=list,
        description="Word-level timing information",
    )
    blob_path: str | None = Field(
        default=None,
        description="Path to detailed JSON in blob storage",
    )

    def get_word_at_timestamp(self, timestamp: float) -> str | None:
        """Get the word being spoken at a specific timestamp.

        Args:
            timestamp: Time in seconds.

        Returns:
            The word at that time, or None if not found.
        """
        for word in self.word_timestamps:
            if word.start_time <= timestamp < word.end_time:
                return word.word
        return None

    def get_text_in_range(self, start: float, end: float) -> str:
        """Get text spoken within a time range.

        Args:
            start: Start time in seconds.
            end: End time in seconds.

        Returns:
            Concatenated words within the range.
        """
        words = [
            w.word
            for w in self.word_timestamps
            if w.start_time >= start and w.end_time <= end
        ]
        return " ".join(words)

    @property
    def word_count(self) -> int:
        """Get number of words in this chunk."""
        if self.word_timestamps:
            return len(self.word_timestamps)
        return len(self.text.split())


class FrameChunk(BaseChunk):
    """A single video frame extracted for visual analysis.

    Frames are extracted at configurable intervals and can be
    analyzed by vision models for content understanding.
    """

    modality: Modality = Field(default=Modality.FRAME, frozen=True)
    frame_number: int = Field(
        ge=0,
        description="Sequential frame number in extraction order",
    )
    blob_path: str = Field(description="Path to full-resolution image in blob storage")
    thumbnail_path: str = Field(description="Path to thumbnail in blob storage")
    description: str | None = Field(
        default=None,
        description="AI-generated description of frame content",
    )
    width: int = Field(gt=0, description="Frame width in pixels")
    height: int = Field(gt=0, description="Frame height in pixels")

    @property
    def aspect_ratio(self) -> float:
        """Calculate aspect ratio (width / height)."""
        return self.width / self.height

    @property
    def resolution(self) -> str:
        """Get resolution as WxH string."""
        return f"{self.width}x{self.height}"

    def with_description(self, description: str) -> Self:
        """Create a copy with an AI-generated description.

        Args:
            description: The AI-generated description.

        Returns:
            New FrameChunk with the description set.
        """
        return self.model_copy(update={"description": description})


class AudioChunk(BaseChunk):
    """A segment of audio for acoustic analysis.

    Audio chunks can be used for music detection, speaker
    identification, or other audio-specific analysis.
    """

    modality: Modality = Field(default=Modality.AUDIO, frozen=True)
    blob_path: str = Field(description="Path to audio segment in blob storage")
    format: str = Field(default="mp3", description="Audio format (mp3, wav, etc.)")
    sample_rate: int = Field(
        default=44100,
        gt=0,
        description="Sample rate in Hz",
    )
    channels: int = Field(
        default=1,
        ge=1,
        le=8,
        description="Number of audio channels",
    )

    @property
    def is_stereo(self) -> bool:
        """Check if audio is stereo."""
        return self.channels >= 2


class VideoChunk(BaseChunk):
    """A segment of video for multimodal LLM analysis.

    Video chunks contain actual video segments that can be sent directly
    to multimodal LLMs (like Gemini, GPT-4V with video, Claude with video)
    for rich contextual understanding that combines visual motion,
    audio, and temporal context.

    This is particularly useful for:
    - Understanding actions and movements
    - Analyzing transitions and temporal relationships
    - Capturing context that static frames miss
    - Direct video Q&A with multimodal models
    """

    modality: Modality = Field(default=Modality.VIDEO, frozen=True)
    blob_path: str = Field(description="Path to video segment in blob storage")
    thumbnail_path: str = Field(
        description="Path to representative thumbnail in blob storage"
    )
    format: str = Field(default="mp4", description="Video format (mp4, webm, etc.)")
    width: int = Field(gt=0, description="Video width in pixels")
    height: int = Field(gt=0, description="Video height in pixels")
    fps: float = Field(gt=0, description="Frames per second")
    has_audio: bool = Field(
        default=True,
        description="Whether this chunk includes audio track",
    )
    codec: str = Field(default="h264", description="Video codec used")
    size_bytes: int = Field(ge=0, description="File size in bytes")
    description: str | None = Field(
        default=None,
        description="AI-generated description of video segment content",
    )

    @property
    def aspect_ratio(self) -> float:
        """Calculate aspect ratio (width / height)."""
        return self.width / self.height

    @property
    def resolution(self) -> str:
        """Get resolution as WxH string."""
        return f"{self.width}x{self.height}"

    @property
    def size_mb(self) -> float:
        """Get size in megabytes."""
        return self.size_bytes / (1024 * 1024)

    def is_within_size_limit(self, max_mb: float = 20.0) -> bool:
        """Check if chunk is within a size limit (useful for API constraints).

        Args:
            max_mb: Maximum size in megabytes.

        Returns:
            True if within limit.
        """
        return self.size_mb <= max_mb

    @property
    def frame_count(self) -> int:
        """Estimate total frame count in this chunk."""
        return int(self.duration_seconds * self.fps)

    def with_description(self, description: str) -> Self:
        """Create a copy with an AI-generated description.

        Args:
            description: The AI-generated description.

        Returns:
            New VideoChunk with the description set.
        """
        return self.model_copy(update={"description": description})


# Type alias for any chunk type
AnyChunk = TranscriptChunk | FrameChunk | AudioChunk | VideoChunk
