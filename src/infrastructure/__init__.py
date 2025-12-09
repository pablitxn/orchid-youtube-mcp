"""Infrastructure layer - external service implementations."""

from src.infrastructure.embeddings import (
    CLIPEmbeddingService,
    EmbeddingModality,
    EmbeddingResult,
    EmbeddingServiceBase,
    OpenAIEmbeddingService,
)
from src.infrastructure.factory import (
    InfrastructureFactory,
    get_factory,
    reset_factory,
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
    OpenAILLMService,
)
from src.infrastructure.transcription import (
    OpenAIWhisperTranscription,
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionServiceBase,
    TranscriptionWord,
)
from src.infrastructure.video import (
    ExtractedFrame,
    FFmpegFrameExtractor,
    FFmpegVideoChunker,
    FrameExtractorBase,
    VideoChunkerBase,
    VideoInfo,
    VideoSegment,
)
from src.infrastructure.youtube import (
    DownloadError,
    DownloadResult,
    SubtitleTrack,
    VideoNotFoundError,
    YouTubeDownloaderBase,
    YouTubeMetadata,
    YtDlpDownloader,
)

__all__ = [
    # Factory
    "InfrastructureFactory",
    "get_factory",
    "reset_factory",
    # Transcription
    "TranscriptionServiceBase",
    "TranscriptionResult",
    "TranscriptionSegment",
    "TranscriptionWord",
    "OpenAIWhisperTranscription",
    # Embeddings
    "EmbeddingServiceBase",
    "EmbeddingResult",
    "EmbeddingModality",
    "OpenAIEmbeddingService",
    "CLIPEmbeddingService",
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
    "OpenAILLMService",
    # YouTube
    "YouTubeDownloaderBase",
    "YouTubeMetadata",
    "SubtitleTrack",
    "DownloadResult",
    "YtDlpDownloader",
    "DownloadError",
    "VideoNotFoundError",
    # Video
    "FrameExtractorBase",
    "VideoChunkerBase",
    "VideoInfo",
    "ExtractedFrame",
    "VideoSegment",
    "FFmpegFrameExtractor",
    "FFmpegVideoChunker",
]
