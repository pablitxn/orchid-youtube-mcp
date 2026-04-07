"""Data Transfer Objects for application layer."""

from src.application.dtos.audio_download import (
    AudioDownloadBatchRequest,
    AudioDownloadBatchResponse,
    AudioDownloadBatchStatus,
    AudioDownloadItemResponse,
    AudioDownloadItemStatus,
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

__all__ = [
    # Audio download DTOs
    "AudioDownloadBatchRequest",
    "AudioDownloadBatchResponse",
    "AudioDownloadBatchStatus",
    "AudioDownloadItemResponse",
    "AudioDownloadItemStatus",
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
]
