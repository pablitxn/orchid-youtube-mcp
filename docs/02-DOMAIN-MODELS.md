# Domain Models

## Overview

The domain layer contains pure business entities that represent the core concepts of the YouTube RAG system. These models are free from infrastructure concerns and define the vocabulary of the business domain.

## Entity Relationship Diagram

```
┌───────────────────────────────────────────────────────────────────────────────┐
│                                                                               │
│  ┌──────────────────┐         1:N         ┌──────────────────┐               │
│  │   VideoMetadata  │◄────────────────────│      Chunk       │               │
│  │                  │                     │   (abstract)     │               │
│  │  - id            │                     │                  │               │
│  │  - youtube_id    │                     │  - id            │               │
│  │  - title         │                     │  - video_id      │               │
│  │  - status        │                     │  - start_time    │               │
│  │  - ...           │                     │  - end_time      │               │
│  └──────────────────┘                     └────────┬─────────┘               │
│           │                                        │                          │
│           │                    ┌───────────────────┼───────────────────┐     │
│           │                    │          │        │        │          │     │
│           │                    ▼          ▼        ▼        ▼          ▼     │
│           │             ┌──────────┐┌──────────┐┌──────────┐┌──────────┐     │
│           │             │Transcript││  Frame   ││  Audio   ││  Video   │     │
│           │             │  Chunk   ││  Chunk   ││  Chunk   ││  Chunk   │     │
│           │             └──────────┘└──────────┘└──────────┘└──────────┘     │
│           │                    │          │        │        │                 │
│           │                    └──────────┴────────┴────────┘                 │
│           │                                        │                          │
│           │                                        │ 1:1                      │
│           │                                        ▼                          │
│           │                              ┌──────────────────┐                │
│           │                              │ EmbeddingVector  │                │
│           │                              │                  │                │
│           │                              │  - id            │                │
│           │                              │  - chunk_id      │                │
│           │                              │  - vector        │                │
│           │                              │  - modality      │                │
│           │                              └──────────────────┘                │
│           │                                                                   │
│           │         1:N          ┌──────────────────┐                        │
│           └──────────────────────│  SourceCitation  │                        │
│                                  │                  │                        │
│                                  │  - id            │                        │
│                                  │  - video_id      │                        │
│                                  │  - chunk_ids     │                        │
│                                  │  - timestamp     │                        │
│                                  └──────────────────┘                        │
│                                                                               │
└───────────────────────────────────────────────────────────────────────────────┘
```

---

## Core Entities

### VideoMetadata

Represents an indexed YouTube video with all its metadata and processing status.

```python
from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional


class VideoStatus(str, Enum):
    """Lifecycle status of a video in the system."""
    PENDING = "pending"           # Queued for processing
    DOWNLOADING = "downloading"   # Currently downloading from YouTube
    TRANSCRIBING = "transcribing" # Extracting transcript
    EXTRACTING = "extracting"     # Extracting frames/audio
    EMBEDDING = "embedding"       # Generating embeddings
    READY = "ready"               # Fully processed and queryable
    FAILED = "failed"             # Processing failed


class VideoMetadata(BaseModel):
    """
    Core entity representing an indexed YouTube video.

    This is the aggregate root for video-related operations.
    All chunks and embeddings are associated with a video through video_id.
    """
    id: str = Field(
        description="Internal UUID for this video record"
    )
    youtube_id: str = Field(
        description="YouTube video ID (the 'v' parameter from URL)"
    )
    youtube_url: str = Field(
        description="Full YouTube URL"
    )
    title: str = Field(
        description="Video title from YouTube"
    )
    description: str = Field(
        default="",
        description="Video description from YouTube"
    )
    duration_seconds: int = Field(
        description="Total video duration in seconds"
    )
    channel_name: str = Field(
        description="Name of the YouTube channel"
    )
    channel_id: str = Field(
        description="YouTube channel ID"
    )
    upload_date: datetime = Field(
        description="When the video was uploaded to YouTube"
    )
    thumbnail_url: str = Field(
        description="URL to video thumbnail"
    )
    language: Optional[str] = Field(
        default=None,
        description="Detected/specified primary language (ISO 639-1)"
    )
    status: VideoStatus = Field(
        default=VideoStatus.PENDING,
        description="Current processing status"
    )
    created_at: datetime = Field(
        description="When this record was created in our system"
    )
    updated_at: datetime = Field(
        description="Last update timestamp"
    )
    error_message: Optional[str] = Field(
        default=None,
        description="Error details if status is FAILED"
    )

    # Processing metadata
    blob_path_video: Optional[str] = Field(
        default=None,
        description="Path to video file in blob storage"
    )
    blob_path_audio: Optional[str] = Field(
        default=None,
        description="Path to audio file in blob storage"
    )
    blob_path_metadata: Optional[str] = Field(
        default=None,
        description="Path to metadata JSON in blob storage"
    )

    # Statistics (populated after processing)
    transcript_chunk_count: int = Field(
        default=0,
        description="Number of transcript chunks created"
    )
    frame_chunk_count: int = Field(
        default=0,
        description="Number of frame chunks created"
    )
    audio_chunk_count: int = Field(
        default=0,
        description="Number of audio chunks created"
    )
    video_chunk_count: int = Field(
        default=0,
        description="Number of video chunks created"
    )

    class Config:
        use_enum_values = True
```

---

### Chunk Models

Chunks represent indexed segments of video content. Each chunk has temporal positioning (start/end times) and modality-specific data.

#### Base Chunk

```python
from abc import ABC
from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class Modality(str, Enum):
    """Content modality type."""
    TRANSCRIPT = "transcript"
    FRAME = "frame"
    AUDIO = "audio"
    VIDEO = "video"  # For future video segment support


class BaseChunk(BaseModel, ABC):
    """
    Abstract base class for all chunk types.

    Chunks represent temporally-positioned segments of video content
    that can be independently embedded and retrieved.
    """
    id: str = Field(
        description="Unique chunk identifier"
    )
    video_id: str = Field(
        description="Reference to parent VideoMetadata"
    )
    modality: Modality = Field(
        description="Type of content this chunk represents"
    )
    start_time: float = Field(
        description="Start time in seconds from video beginning"
    )
    end_time: float = Field(
        description="End time in seconds from video beginning"
    )
    created_at: datetime = Field(
        description="When this chunk was created"
    )

    def duration_seconds(self) -> float:
        """Calculate chunk duration."""
        return self.end_time - self.start_time

    def overlaps_with(self, other: "BaseChunk") -> bool:
        """Check if this chunk overlaps temporally with another."""
        return not (self.end_time <= other.start_time or self.start_time >= other.end_time)

    def contains_timestamp(self, timestamp: float) -> bool:
        """Check if a timestamp falls within this chunk."""
        return self.start_time <= timestamp < self.end_time
```

#### TranscriptChunk

```python
class WordTimestamp(BaseModel):
    """Individual word with precise timing."""
    word: str
    start_time: float
    end_time: float
    confidence: float = Field(ge=0.0, le=1.0)


class TranscriptChunk(BaseChunk):
    """
    A segment of transcribed speech.

    Contains the text content along with word-level timestamps
    for precise citation and navigation.
    """
    modality: Modality = Modality.TRANSCRIPT

    text: str = Field(
        description="Transcribed text content"
    )
    language: str = Field(
        description="Detected language (ISO 639-1)"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Overall transcription confidence"
    )
    word_timestamps: list[WordTimestamp] = Field(
        default_factory=list,
        description="Word-level timing information"
    )
    blob_path: Optional[str] = Field(
        default=None,
        description="Path to detailed JSON in blob storage"
    )

    def get_text_at_timestamp(self, timestamp: float) -> Optional[str]:
        """Get the word being spoken at a specific timestamp."""
        for word in self.word_timestamps:
            if word.start_time <= timestamp < word.end_time:
                return word.word
        return None

    def get_text_in_range(self, start: float, end: float) -> str:
        """Get text spoken within a time range."""
        words = [
            w.word for w in self.word_timestamps
            if w.start_time >= start and w.end_time <= end
        ]
        return " ".join(words)
```

#### FrameChunk

```python
class FrameChunk(BaseChunk):
    """
    A single video frame extracted for visual analysis.

    Frames are extracted at configurable intervals and can be
    analyzed by vision models for content understanding.
    """
    modality: Modality = Modality.FRAME

    frame_number: int = Field(
        description="Sequential frame number in extraction order"
    )
    blob_path: str = Field(
        description="Path to full-resolution image in blob storage"
    )
    thumbnail_path: str = Field(
        description="Path to thumbnail in blob storage"
    )
    description: Optional[str] = Field(
        default=None,
        description="AI-generated description of frame content"
    )
    width: int = Field(
        description="Frame width in pixels"
    )
    height: int = Field(
        description="Frame height in pixels"
    )

    @property
    def aspect_ratio(self) -> float:
        """Calculate aspect ratio."""
        return self.width / self.height if self.height > 0 else 0
```

#### AudioChunk

```python
class AudioChunk(BaseChunk):
    """
    A segment of audio for acoustic analysis.

    Audio chunks can be used for music detection, speaker
    identification, or other audio-specific analysis.
    """
    modality: Modality = Modality.AUDIO

    blob_path: str = Field(
        description="Path to audio segment in blob storage"
    )
    format: str = Field(
        default="mp3",
        description="Audio format (mp3, wav, etc.)"
    )
    sample_rate: int = Field(
        default=44100,
        description="Sample rate in Hz"
    )
    channels: int = Field(
        default=1,
        description="Number of audio channels"
    )
```

#### VideoChunk

```python
class VideoChunk(BaseChunk):
    """
    A segment of video for multimodal LLM analysis.

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
    modality: Modality = Modality.VIDEO

    blob_path: str = Field(
        description="Path to video segment in blob storage"
    )
    thumbnail_path: str = Field(
        description="Path to representative thumbnail in blob storage"
    )
    format: str = Field(
        default="mp4",
        description="Video format (mp4, webm, etc.)"
    )
    width: int = Field(
        description="Video width in pixels"
    )
    height: int = Field(
        description="Video height in pixels"
    )
    fps: float = Field(
        description="Frames per second"
    )
    has_audio: bool = Field(
        default=True,
        description="Whether this chunk includes audio track"
    )
    codec: str = Field(
        default="h264",
        description="Video codec used"
    )
    size_bytes: int = Field(
        description="File size in bytes"
    )
    description: Optional[str] = Field(
        default=None,
        description="AI-generated description of video segment content"
    )

    @property
    def aspect_ratio(self) -> float:
        """Calculate aspect ratio."""
        return self.width / self.height if self.height > 0 else 0

    @property
    def size_mb(self) -> float:
        """Get size in megabytes."""
        return self.size_bytes / (1024 * 1024)

    def is_within_size_limit(self, max_mb: float = 20.0) -> bool:
        """Check if chunk is within a size limit (useful for API constraints)."""
        return self.size_mb <= max_mb
```

---

### Embedding Models

```python
from typing import List


class EmbeddingVector(BaseModel):
    """
    A vector embedding associated with a chunk.

    Embeddings are stored in the vector database and used
    for semantic similarity search.
    """
    id: str = Field(
        description="Unique embedding identifier"
    )
    chunk_id: str = Field(
        description="Reference to source chunk"
    )
    video_id: str = Field(
        description="Reference to parent video (denormalized for query efficiency)"
    )
    modality: Modality = Field(
        description="Modality of the source chunk"
    )
    vector: List[float] = Field(
        description="The embedding vector"
    )
    model: str = Field(
        description="Model used to generate this embedding"
    )
    dimensions: int = Field(
        description="Vector dimensionality"
    )
    created_at: datetime = Field(
        description="When this embedding was created"
    )

    def __len__(self) -> int:
        return len(self.vector)
```

---

### Citation Models

```python
from typing import Dict, List


class TimestampRange(BaseModel):
    """A time range within a video."""
    start_time: float = Field(
        ge=0,
        description="Start time in seconds"
    )
    end_time: float = Field(
        ge=0,
        description="End time in seconds"
    )

    def duration_seconds(self) -> float:
        return self.end_time - self.start_time

    def format_display(self) -> str:
        """Format as MM:SS - MM:SS for display."""
        def fmt(s: float) -> str:
            minutes = int(s // 60)
            seconds = int(s % 60)
            return f"{minutes:02d}:{seconds:02d}"
        return f"{fmt(self.start_time)} - {fmt(self.end_time)}"

    def to_youtube_url_param(self) -> str:
        """Generate YouTube timestamp parameter."""
        return f"t={int(self.start_time)}"


class SourceCitation(BaseModel):
    """
    A citation pointing to source material in a video.

    Citations are generated during query responses to provide
    verifiable references to the original content.
    """
    id: str = Field(
        description="Unique citation identifier"
    )
    video_id: str = Field(
        description="Reference to source video"
    )
    chunk_ids: List[str] = Field(
        description="Chunks that support this citation"
    )
    modality: Modality = Field(
        description="Primary modality of cited content"
    )
    timestamp_range: TimestampRange = Field(
        description="Temporal location in video"
    )
    relevance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="How relevant this citation is to the query"
    )
    content_preview: str = Field(
        description="Short preview of cited content"
    )
    source_urls: Dict[str, str] = Field(
        default_factory=dict,
        description="Presigned URLs for accessing sources by modality"
    )

    def youtube_url_with_timestamp(self, base_url: str) -> str:
        """Generate YouTube URL that jumps to this citation."""
        param = self.timestamp_range.to_youtube_url_param()
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}{param}"
```

---

## Domain Exceptions

```python
class DomainException(Exception):
    """Base exception for domain errors."""
    pass


class VideoNotFoundException(DomainException):
    """Raised when a requested video is not found."""
    def __init__(self, video_id: str):
        self.video_id = video_id
        super().__init__(f"Video not found: {video_id}")


class VideoNotReadyException(DomainException):
    """Raised when attempting to query a video that isn't fully processed."""
    def __init__(self, video_id: str, status: VideoStatus):
        self.video_id = video_id
        self.status = status
        super().__init__(f"Video {video_id} is not ready. Current status: {status}")


class ChunkNotFoundException(DomainException):
    """Raised when a requested chunk is not found."""
    def __init__(self, chunk_id: str):
        self.chunk_id = chunk_id
        super().__init__(f"Chunk not found: {chunk_id}")


class InvalidYouTubeUrlException(DomainException):
    """Raised when a YouTube URL is invalid or unsupported."""
    def __init__(self, url: str, reason: str = "Invalid URL"):
        self.url = url
        self.reason = reason
        super().__init__(f"Invalid YouTube URL '{url}': {reason}")


class IngestionException(DomainException):
    """Raised when video ingestion fails."""
    def __init__(self, video_id: str, stage: str, reason: str):
        self.video_id = video_id
        self.stage = stage
        self.reason = reason
        super().__init__(f"Ingestion failed for {video_id} at {stage}: {reason}")


class EmbeddingException(DomainException):
    """Raised when embedding generation fails."""
    def __init__(self, chunk_id: str, reason: str):
        self.chunk_id = chunk_id
        self.reason = reason
        super().__init__(f"Embedding failed for chunk {chunk_id}: {reason}")


class QueryException(DomainException):
    """Raised when a query operation fails."""
    def __init__(self, video_id: str, reason: str):
        self.video_id = video_id
        self.reason = reason
        super().__init__(f"Query failed for video {video_id}: {reason}")
```

---

## Value Objects

```python
class YouTubeVideoId(BaseModel):
    """
    Value object representing a validated YouTube video ID.

    Ensures the ID follows YouTube's format (11 characters, alphanumeric + _-).
    """
    value: str = Field(
        min_length=11,
        max_length=11,
        pattern=r"^[a-zA-Z0-9_-]{11}$"
    )

    @classmethod
    def from_url(cls, url: str) -> "YouTubeVideoId":
        """Extract video ID from various YouTube URL formats."""
        import re

        patterns = [
            r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
            r"(?:embed/)([a-zA-Z0-9_-]{11})",
            r"(?:shorts/)([a-zA-Z0-9_-]{11})",
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return cls(value=match.group(1))

        raise InvalidYouTubeUrlException(url, "Could not extract video ID")

    def to_url(self) -> str:
        """Convert to standard YouTube watch URL."""
        return f"https://www.youtube.com/watch?v={self.value}"


class ChunkingConfig(BaseModel):
    """Configuration for chunk generation."""
    transcript_chunk_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Duration of each transcript chunk"
    )
    transcript_overlap_seconds: int = Field(
        default=5,
        ge=0,
        le=30,
        description="Overlap between consecutive transcript chunks"
    )
    frame_interval_seconds: float = Field(
        default=2.0,
        ge=0.5,
        le=60,
        description="Interval between extracted frames"
    )
    audio_chunk_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Duration of each audio chunk"
    )
    video_chunk_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Duration of each video chunk for multimodal LLMs"
    )
    video_chunk_overlap_seconds: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Overlap between consecutive video chunks"
    )
    video_chunk_max_size_mb: float = Field(
        default=20.0,
        ge=1.0,
        le=100.0,
        description="Maximum size per video chunk in MB"
    )
```

---

## Model Relationships Summary

| Entity | Relationships |
|--------|---------------|
| **VideoMetadata** | Has many TranscriptChunks, FrameChunks, AudioChunks, VideoChunks, SourceCitations |
| **TranscriptChunk** | Belongs to VideoMetadata, Has one EmbeddingVector |
| **FrameChunk** | Belongs to VideoMetadata, Has one EmbeddingVector |
| **AudioChunk** | Belongs to VideoMetadata, Has one EmbeddingVector |
| **VideoChunk** | Belongs to VideoMetadata, Has one EmbeddingVector (via description text) |
| **EmbeddingVector** | Belongs to one Chunk (any modality), References VideoMetadata |
| **SourceCitation** | Belongs to VideoMetadata, References multiple Chunks |

---

## Storage Mapping

| Entity | Primary Storage | Secondary Storage |
|--------|----------------|-------------------|
| VideoMetadata | MongoDB | - |
| TranscriptChunk | MongoDB | Blob Storage (detailed JSON) |
| FrameChunk | MongoDB | Blob Storage (images) |
| AudioChunk | MongoDB | Blob Storage (audio files) |
| VideoChunk | MongoDB | Blob Storage (video segments) |
| EmbeddingVector | Qdrant | - |
| SourceCitation | MongoDB (cached) | Generated on-demand |

---

## Multimodal LLM Compatibility

VideoChunks are designed to be compatible with multimodal LLMs that support video input:

| Provider | Model | Max Video Size | Max Duration | Notes |
|----------|-------|----------------|--------------|-------|
| Google | Gemini 1.5 Pro | 2GB | 1 hour | Native video understanding |
| Google | Gemini 1.5 Flash | 2GB | 1 hour | Faster, lower cost |
| OpenAI | GPT-4o | TBD | TBD | Video support coming |
| Anthropic | Claude | TBD | TBD | Video support coming |

The `VideoChunk.is_within_size_limit()` method helps ensure chunks are within provider constraints.
