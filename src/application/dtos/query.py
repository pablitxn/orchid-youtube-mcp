"""DTOs for video query operations."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from src.commons.model_capabilities import ContentType


class QueryModality(str, Enum):
    """Modalities available for querying."""

    TRANSCRIPT = "transcript"
    FRAME = "frame"
    AUDIO = "audio"
    VIDEO = "video"


class EnabledContentTypes(BaseModel):
    """Content types to include in LLM messages."""

    text: bool = Field(default=True, description="Always include text")
    image: bool = Field(default=False, description="Include images from frames")
    audio: bool = Field(default=False, description="Include audio clips")
    video: bool = Field(default=False, description="Include video segments")

    def to_content_types(self) -> set[ContentType]:
        """Convert to set of ContentType."""
        types = {ContentType.TEXT}
        if self.image:
            types.add(ContentType.IMAGE)
        if self.audio:
            types.add(ContentType.AUDIO)
        if self.video:
            types.add(ContentType.VIDEO)
        return types


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


class SubTaskInfo(BaseModel):
    """Information about a decomposed subtask."""

    id: int = Field(description="Subtask identifier")
    sub_query: str = Field(description="The subtask query")
    target_modality: str = Field(description="Target modality for search")
    chunks_found: int = Field(description="Number of chunks found")
    success: bool = Field(description="Whether subtask succeeded")


class DecompositionInfo(BaseModel):
    """Information about query decomposition."""

    was_decomposed: bool = Field(description="Whether query was decomposed")
    subtask_count: int = Field(default=0, description="Number of subtasks")
    subtasks: list[SubTaskInfo] = Field(
        default_factory=list,
        description="Details of each subtask",
    )
    reasoning: str | None = Field(
        default=None,
        description="Why decomposition was/wasn't used",
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
    decomposition: DecompositionInfo | None = Field(
        default=None,
        description="Query decomposition info if enabled",
    )
    multimodal_content_used: list[str] = Field(
        default_factory=list,
        description="Content types used in LLM context",
    )


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
    # Agentic features
    enable_decomposition: bool = Field(
        default=False,
        description="Enable query decomposition for complex questions",
    )
    enabled_content_types: EnabledContentTypes = Field(
        default_factory=EnabledContentTypes,
        description="Content types to include in LLM context (multimodal)",
    )
    enable_refinement: bool = Field(
        default=False,
        description="Enable confidence-based query refinement",
    )
    confidence_threshold: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Minimum confidence before triggering refinement",
    )
    enable_tools: bool = Field(
        default=False,
        description="Enable internal tool use during answer generation",
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


# Cross-Video Query DTOs


class CrossVideoRequest(BaseModel):
    """Request to query across multiple videos."""

    query: str = Field(
        min_length=1,
        max_length=1000,
        description="Natural language question",
    )
    video_ids: list[str] | None = Field(
        default=None,
        description="Video IDs to search. None = all videos",
    )
    max_videos: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum videos to include in results",
    )
    max_citations_per_video: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum citations per video",
    )
    similarity_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score",
    )
    enabled_content_types: EnabledContentTypes = Field(
        default_factory=EnabledContentTypes,
        description="Content types to include",
    )


class VideoResult(BaseModel):
    """Results from a single video in cross-video query."""

    video_id: str = Field(description="Video identifier")
    video_title: str = Field(description="Video title")
    relevance_score: float = Field(description="Overall relevance to query")
    citations: list[CitationDTO] = Field(description="Citations from this video")
    summary: str | None = Field(
        default=None,
        description="Brief summary of findings from this video",
    )


class CrossVideoResponse(BaseModel):
    """Response from cross-video query."""

    answer: str = Field(description="Synthesized answer across all videos")
    confidence: float = Field(description="Overall confidence")
    video_results: list[VideoResult] = Field(description="Per-video results")
    videos_searched: int = Field(description="Number of videos searched")
    total_citations: int = Field(description="Total citations across all videos")
    processing_time_ms: int = Field(description="Total processing time")


# Tool Use DTOs


class ToolCall(BaseModel):
    """A tool call made during answer generation."""

    tool_name: str = Field(description="Name of the tool called")
    arguments: dict[str, str | int | float | bool] = Field(
        description="Arguments passed to tool"
    )
    result_summary: str = Field(description="Brief summary of tool result")
    timestamp_ms: int = Field(description="When the tool was called")


class RefinementInfo(BaseModel):
    """Information about query refinement attempts."""

    was_refined: bool = Field(description="Whether refinement was triggered")
    original_confidence: float = Field(description="Confidence before refinement")
    final_confidence: float = Field(description="Confidence after refinement")
    refinement_strategy: str | None = Field(
        default=None,
        description="Strategy used (expand_query, adjacent_chunks, lower_threshold)",
    )
    iterations: int = Field(default=1, description="Number of refinement iterations")
