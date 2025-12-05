"""Domain layer - business models and logic."""

from src.domain.exceptions import (
    ChunkNotFoundException,
    DomainException,
    EmbeddingException,
    IngestionException,
    InvalidYouTubeUrlException,
    QueryException,
    VideoNotFoundException,
    VideoNotReadyException,
)
from src.domain.models import (
    AnyChunk,
    AudioChunk,
    BaseChunk,
    CitationGroup,
    EmbeddingVector,
    FrameChunk,
    Modality,
    SourceCitation,
    TimestampRange,
    TranscriptChunk,
    VideoChunk,
    VideoMetadata,
    VideoStatus,
    WordTimestamp,
)
from src.domain.value_objects import ChunkingConfig, YouTubeVideoId

__all__ = [
    # Exceptions
    "DomainException",
    "VideoNotFoundException",
    "VideoNotReadyException",
    "ChunkNotFoundException",
    "InvalidYouTubeUrlException",
    "IngestionException",
    "EmbeddingException",
    "QueryException",
    # Video
    "VideoMetadata",
    "VideoStatus",
    # Chunks
    "Modality",
    "BaseChunk",
    "TranscriptChunk",
    "FrameChunk",
    "AudioChunk",
    "VideoChunk",
    "WordTimestamp",
    "AnyChunk",
    # Citation
    "TimestampRange",
    "SourceCitation",
    "CitationGroup",
    # Embedding
    "EmbeddingVector",
    # Value Objects
    "YouTubeVideoId",
    "ChunkingConfig",
]
