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
    DecompositionInfo,
    EnabledContentTypes,
    GetSourcesRequest,
    QueryMetadata,
    QueryModality,
    QueryVideoRequest,
    QueryVideoResponse,
    SourcesResponse,
    SubTaskInfo,
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
    "DecompositionInfo",
    "EnabledContentTypes",
    "GetSourcesRequest",
    "QueryMetadata",
    "QueryModality",
    "QueryVideoRequest",
    "QueryVideoResponse",
    "SourcesResponse",
    "SubTaskInfo",
]
