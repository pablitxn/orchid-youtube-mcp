"""Domain exceptions for the YouTube RAG system."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.domain.models.video import VideoStatus


class DomainException(Exception):
    """Base exception for domain errors."""


class VideoNotFoundException(DomainException):
    """Raised when a requested video is not found."""

    def __init__(self, video_id: str) -> None:
        self.video_id = video_id
        super().__init__(f"Video not found: {video_id}")


class VideoNotReadyException(DomainException):
    """Raised when attempting to query a video that isn't fully processed."""

    def __init__(self, video_id: str, status: VideoStatus) -> None:
        self.video_id = video_id
        self.status = status
        super().__init__(f"Video {video_id} is not ready. Current status: {status}")


class ChunkNotFoundException(DomainException):
    """Raised when a requested chunk is not found."""

    def __init__(self, chunk_id: str) -> None:
        self.chunk_id = chunk_id
        super().__init__(f"Chunk not found: {chunk_id}")


class InvalidYouTubeUrlException(DomainException):
    """Raised when a YouTube URL is invalid or unsupported."""

    def __init__(self, url: str, reason: str = "Invalid URL") -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Invalid YouTube URL '{url}': {reason}")


class IngestionException(DomainException):
    """Raised when video ingestion fails."""

    def __init__(self, video_id: str, stage: str, reason: str) -> None:
        self.video_id = video_id
        self.stage = stage
        self.reason = reason
        super().__init__(f"Ingestion failed for {video_id} at {stage}: {reason}")


class EmbeddingException(DomainException):
    """Raised when embedding generation fails."""

    def __init__(self, chunk_id: str, reason: str) -> None:
        self.chunk_id = chunk_id
        self.reason = reason
        super().__init__(f"Embedding failed for chunk {chunk_id}: {reason}")


class QueryException(DomainException):
    """Raised when a query operation fails."""

    def __init__(self, video_id: str, reason: str) -> None:
        self.video_id = video_id
        self.reason = reason
        super().__init__(f"Query failed for video {video_id}: {reason}")
