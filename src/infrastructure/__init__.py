"""Infrastructure layer - external service implementations."""

from src.infrastructure.embeddings import (
    EmbeddingModality,
    EmbeddingResult,
    EmbeddingServiceBase,
)
from src.infrastructure.llm import (
    FunctionCall,
    FunctionDefinition,
    FunctionParameter,
    LLMResponse,
    LLMResponseWithTools,
    LLMServiceBase,
    LLMUsage,
    Message,
    MessageRole,
)
from src.infrastructure.transcription import (
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionServiceBase,
    TranscriptionWord,
)
from src.infrastructure.video import (
    ExtractedFrame,
    FrameExtractorBase,
    VideoChunkerBase,
    VideoInfo,
    VideoSegment,
)
from src.infrastructure.youtube import (
    DownloadResult,
    SubtitleTrack,
    YouTubeDownloaderBase,
    YouTubeMetadata,
)

__all__ = [
    # Transcription
    "TranscriptionServiceBase",
    "TranscriptionResult",
    "TranscriptionSegment",
    "TranscriptionWord",
    # Embeddings
    "EmbeddingServiceBase",
    "EmbeddingResult",
    "EmbeddingModality",
    # LLM
    "LLMServiceBase",
    "LLMResponse",
    "LLMResponseWithTools",
    "LLMUsage",
    "Message",
    "MessageRole",
    "FunctionDefinition",
    "FunctionParameter",
    "FunctionCall",
    # YouTube
    "YouTubeDownloaderBase",
    "YouTubeMetadata",
    "SubtitleTrack",
    "DownloadResult",
    # Video
    "FrameExtractorBase",
    "VideoChunkerBase",
    "VideoInfo",
    "ExtractedFrame",
    "VideoSegment",
]
