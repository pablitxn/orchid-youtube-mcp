"""Data Transfer Objects for application layer."""

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
