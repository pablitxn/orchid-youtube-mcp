"""DTOs for video query operations."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class QueryModality(str, Enum):
    """Modalities available for querying."""

    TRANSCRIPT = "transcript"
    FRAME = "frame"
    AUDIO = "audio"
    VIDEO = "video"


class TimestampRangeDTO(BaseModel):
    """Timestamp range in a video."""

    start_time: float = Field(ge=0, description="Start time in seconds")
    end_time: float = Field(ge=0, description="End time in seconds")
    display: str = Field(description="Human-readable time range")


class CitationDTO(BaseModel):
    """A source citation for query results."""

    id: str = Field(description="Citation identifier")
    modality: QueryModality = Field(description="Type of source material")
    timestamp_range: TimestampRangeDTO = Field(description="Location in video")
    content_preview: str = Field(description="Preview of cited content")
    relevance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="How relevant this citation is to the query",
    )
    youtube_url: str | None = Field(
        default=None,
        description="Direct YouTube link with timestamp",
    )
    source_url: str | None = Field(
        default=None,
        description="Presigned URL for source artifact",
    )


class QueryMetadata(BaseModel):
    """Metadata about the query execution."""

    video_id: str = Field(description="ID of the queried video")
    video_title: str = Field(description="Title of the queried video")
    modalities_searched: list[QueryModality] = Field(
        description="Which modalities were searched",
    )
    chunks_analyzed: int = Field(description="Number of chunks analyzed")
    processing_time_ms: int = Field(description="Total processing time in milliseconds")


class QueryVideoRequest(BaseModel):
    """Request to query a video's content."""

    query: str = Field(
        min_length=1,
        max_length=1000,
        description="Natural language question about the video",
    )
    modalities: list[QueryModality] = Field(
        default=[QueryModality.TRANSCRIPT, QueryModality.FRAME],
        description="Which modalities to search across",
    )
    max_citations: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of citations to return",
    )
    include_reasoning: bool = Field(
        default=True,
        description="Whether to include explanation of reasoning",
    )
    similarity_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for results",
    )


class QueryVideoResponse(BaseModel):
    """Response from querying a video."""

    answer: str = Field(description="Answer to the query based on video content")
    reasoning: str | None = Field(
        default=None,
        description="Explanation of how the answer was derived",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score for the answer",
    )
    citations: list[CitationDTO] = Field(
        default_factory=list,
        description="Source citations supporting the answer",
    )
    query_metadata: QueryMetadata = Field(
        description="Information about query execution",
    )


class SourceArtifact(BaseModel):
    """A source artifact with presigned URL."""

    type: str = Field(description="Artifact type (transcript_text, frame_image)")
    url: str | None = Field(default=None, description="Presigned URL to access")
    content: str | None = Field(default=None, description="Text content if applicable")


class SourceDetail(BaseModel):
    """Detailed source information for a citation."""

    citation_id: str = Field(description="Citation identifier")
    modality: QueryModality = Field(description="Source modality")
    timestamp_range: TimestampRangeDTO = Field(description="Time range in video")
    artifacts: dict[str, SourceArtifact] = Field(
        default_factory=dict,
        description="Available artifacts by type",
    )


class GetSourcesRequest(BaseModel):
    """Request to get source details for citations."""

    citation_ids: list[str] = Field(
        min_length=1,
        description="Citation IDs to retrieve sources for",
    )
    include_artifacts: list[str] = Field(
        default=["transcript_text", "thumbnail"],
        description="Which artifact types to include",
    )
    url_expiry_minutes: int = Field(
        default=60,
        ge=5,
        le=1440,
        description="How long presigned URLs should remain valid",
    )


class SourcesResponse(BaseModel):
    """Response with detailed source information."""

    sources: list[SourceDetail] = Field(description="Detailed source information")
    expires_at: datetime = Field(description="When presigned URLs expire")
