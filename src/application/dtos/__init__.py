"""Data Transfer Objects for application layer."""

from src.application.dtos.agent import (
    AgentChatMessageInput,
    AgentChatResult,
    AgentToolTrace,
)
from src.application.dtos.ingestion import (
    IngestionProgress,
    IngestionStatus,
    IngestVideoRequest,
    IngestVideoResponse,
    ProcessingStep,
)
from src.application.dtos.query import (
    CitationDTO,
    CrossVideoRequest,
    CrossVideoResponse,
    DecompositionInfo,
    EnabledContentTypes,
    GetSourcesRequest,
    QueryMetadata,
    QueryModality,
    QueryVideoRequest,
    QueryVideoResponse,
    RefinementInfo,
    SourcesResponse,
    SubTaskInfo,
    ToolCall,
    VideoResult,
)
from src.application.dtos.youtube_auth import (
    ManagedYouTubeCookie,
    YouTubeAuthMode,
    YouTubeAuthStatus,
    YouTubeDownloadTestResult,
)

__all__ = [
    "AgentChatMessageInput",
    "AgentChatResult",
    "AgentToolTrace",
    # Ingestion DTOs
    "IngestVideoRequest",
    "IngestVideoResponse",
    "IngestionProgress",
    "IngestionStatus",
    "ProcessingStep",
    # Query DTOs
    "CitationDTO",
    "CrossVideoRequest",
    "CrossVideoResponse",
    "DecompositionInfo",
    "EnabledContentTypes",
    "GetSourcesRequest",
    "QueryMetadata",
    "QueryModality",
    "QueryVideoRequest",
    "QueryVideoResponse",
    "RefinementInfo",
    "SourcesResponse",
    "SubTaskInfo",
    "ToolCall",
    "VideoResult",
    # YouTube auth DTOs
    "ManagedYouTubeCookie",
    "YouTubeAuthMode",
    "YouTubeAuthStatus",
    "YouTubeDownloadTestResult",
]
