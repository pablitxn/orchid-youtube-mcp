"""Pydantic settings models for application configuration."""

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseModel):
    """Application-level settings."""

    name: str = "youtube-rag-server"
    version: str = "0.1.0"
    environment: Literal["dev", "staging", "prod"] = "dev"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class ServerSettings(BaseModel):
    """HTTP server settings."""

    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1, le=32)
    reload: bool = False
    cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    api_prefix: str = "/v1"
    docs_enabled: bool = True


class BucketSettings(BaseModel):
    """Bucket name configuration."""

    videos: str = "rag-videos"
    chunks: str = "rag-chunks"
    frames: str = "rag-frames"


class BlobStorageSettings(BaseModel):
    """Blob storage settings (MinIO/S3)."""

    provider: Literal["minio", "s3", "gcs", "azure"] = "minio"
    endpoint: str = "localhost:9000"
    access_key: str = ""
    secret_key: str = ""
    use_ssl: bool = False
    region: str = "us-east-1"
    buckets: BucketSettings = Field(default_factory=BucketSettings)
    presigned_url_expiry_seconds: int = 3600


class CollectionSettings(BaseModel):
    """Vector DB collection names."""

    transcripts: str = "transcript_embeddings"
    frames: str = "frame_embeddings"
    videos: str = "video_embeddings"


class VectorDBSettings(BaseModel):
    """Vector database settings (Qdrant)."""

    provider: Literal["qdrant", "pinecone", "weaviate"] = "qdrant"
    host: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334
    api_key: str | None = None
    use_ssl: bool = False
    collections: CollectionSettings = Field(default_factory=CollectionSettings)
    default_limit: int = 10
    score_threshold: float = 0.7


class DocumentCollectionSettings(BaseModel):
    """Document DB collection names."""

    videos: str = "videos"
    transcript_chunks: str = "transcript_chunks"
    frame_chunks: str = "frame_chunks"
    audio_chunks: str = "audio_chunks"
    video_chunks: str = "video_chunks"
    citations: str = "citations"


class DocumentDBSettings(BaseModel):
    """Document database settings (MongoDB)."""

    provider: Literal["mongodb", "postgres"] = "mongodb"
    host: str = "localhost"
    port: int = 27017
    username: str = ""
    password: str = ""
    database: str = "youtube_rag"
    auth_source: str = "admin"
    collections: DocumentCollectionSettings = Field(
        default_factory=DocumentCollectionSettings
    )


class TranscriptionSettings(BaseModel):
    """Transcription service settings."""

    provider: Literal[
        "openai_whisper", "deepgram", "assemblyai", "azure_speech", "google_speech"
    ] = "openai_whisper"
    api_key: str = ""
    model: str = "whisper-1"
    language: str | None = None
    word_timestamps: bool = True
    timeout_seconds: int = 300


class TextEmbeddingSettings(BaseModel):
    """Text embedding settings."""

    provider: Literal["openai", "azure_openai", "cohere", "voyage"] = "openai"
    api_key: str = ""
    endpoint: str | None = None
    deployment: str | None = None
    model: str = "text-embedding-3-small"
    dimensions: int = 1536
    batch_size: int = 100


class ImageEmbeddingSettings(BaseModel):
    """Image embedding settings."""

    provider: Literal["clip", "vertex"] = "clip"
    api_url: str = "http://localhost:8080"
    api_key: str | None = None
    model: str = "ViT-B/32"
    dimensions: int = 512
    batch_size: int = 32


class EmbeddingsSettings(BaseModel):
    """Combined embedding settings."""

    text: TextEmbeddingSettings = Field(default_factory=TextEmbeddingSettings)
    image: ImageEmbeddingSettings = Field(default_factory=ImageEmbeddingSettings)


class LLMSettings(BaseModel):
    """LLM service settings."""

    provider: Literal["openai", "azure_openai", "anthropic", "google"] = "openai"
    api_key: str = ""
    endpoint: str | None = None
    deployment: str | None = None
    model: str = "gpt-4o"
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = 2048
    timeout_seconds: int = 60


class TranscriptChunkingSettings(BaseModel):
    """Transcript chunking configuration."""

    chunk_seconds: int = 30
    overlap_seconds: int = 5


class FrameChunkingSettings(BaseModel):
    """Frame extraction configuration."""

    interval_seconds: float = 2.0


class AudioChunkingSettings(BaseModel):
    """Audio chunking configuration."""

    chunk_seconds: int = 60


class VideoChunkingSettings(BaseModel):
    """Video chunking configuration."""

    chunk_seconds: int = 30
    overlap_seconds: int = 2
    max_size_mb: float = 20.0


class ChunkingSettings(BaseModel):
    """All chunking configurations."""

    transcript: TranscriptChunkingSettings = Field(
        default_factory=TranscriptChunkingSettings
    )
    frame: FrameChunkingSettings = Field(default_factory=FrameChunkingSettings)
    audio: AudioChunkingSettings = Field(default_factory=AudioChunkingSettings)
    video: VideoChunkingSettings = Field(default_factory=VideoChunkingSettings)


class ProcessingSettings(BaseModel):
    """Video processing settings."""

    max_video_duration_seconds: int = 7200  # 2 hours
    max_video_size_mb: int = 2048  # 2 GB
    concurrent_downloads: int = 2
    retry_attempts: int = 3
    retry_delay_seconds: int = 5


class LokiSettings(BaseModel):
    """Loki logging settings."""

    enabled: bool = False
    endpoint: str = "http://localhost:3100"
    batch_size: int = 100
    flush_interval_seconds: int = 5


class MetricsSettings(BaseModel):
    """Metrics settings."""

    enabled: bool = False
    endpoint: str = "http://localhost:9090"


class TelemetrySettings(BaseModel):
    """Telemetry and observability settings."""

    enabled: bool = True
    log_format: Literal["json", "text"] = "json"
    log_level: str = "INFO"
    loki: LokiSettings = Field(default_factory=LokiSettings)
    metrics: MetricsSettings = Field(default_factory=MetricsSettings)


class LimitConfig(BaseModel):
    """Rate limit configuration."""

    requests: int
    window_seconds: int


class RateLimitSettings(BaseModel):
    """Rate limiting settings."""

    enabled: bool = True
    storage: Literal["memory", "redis"] = "memory"
    limits: dict[str, LimitConfig] = Field(
        default_factory=lambda: {
            "ingest": LimitConfig(requests=10, window_seconds=3600),
            "query": LimitConfig(requests=100, window_seconds=60),
            "sources": LimitConfig(requests=200, window_seconds=60),
            "list": LimitConfig(requests=60, window_seconds=60),
            "delete": LimitConfig(requests=30, window_seconds=3600),
        }
    )


class Settings(BaseSettings):
    """Root settings container with environment loading."""

    app: AppSettings = Field(default_factory=AppSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    blob_storage: BlobStorageSettings = Field(default_factory=BlobStorageSettings)
    vector_db: VectorDBSettings = Field(default_factory=VectorDBSettings)
    document_db: DocumentDBSettings = Field(default_factory=DocumentDBSettings)
    transcription: TranscriptionSettings = Field(default_factory=TranscriptionSettings)
    embeddings: EmbeddingsSettings = Field(default_factory=EmbeddingsSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    chunking: ChunkingSettings = Field(default_factory=ChunkingSettings)
    processing: ProcessingSettings = Field(default_factory=ProcessingSettings)
    telemetry: TelemetrySettings = Field(default_factory=TelemetrySettings)
    rate_limiting: RateLimitSettings = Field(default_factory=RateLimitSettings)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="YOUTUBE_RAG__",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore",
    )
