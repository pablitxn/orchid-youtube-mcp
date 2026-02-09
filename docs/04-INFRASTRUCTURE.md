# Infrastructure Services

## Overview

The infrastructure layer provides concrete implementations of external services and storage systems. All components implement abstract base classes (ABCs) to enable:
- Easy testing with mocks
- Provider swapping without code changes
- Clear separation of concerns

---

## Architecture Pattern

```
┌─────────────────────────────────────────────────────────────────┐
│                     Application Layer                            │
│                   (Services, Pipelines)                          │
└──────────────────────────┬──────────────────────────────────────┘
                           │ depends on abstractions
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   Abstract Base Classes                          │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐ │
│  │ BlobStorage │ │  VectorDB   │ │ DocumentDB  │ │    LLM    │ │
│  │    (ABC)    │ │    (ABC)    │ │    (ABC)    │ │   (ABC)   │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘ │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐               │
│  │Transcription│ │  Embedding  │ │  YouTube    │               │
│  │   (ABC)     │ │    (ABC)    │ │ Downloader  │               │
│  └─────────────┘ └─────────────┘ └─────────────┘               │
└──────────────────────────┬──────────────────────────────────────┘
                           │ implemented by
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  Concrete Implementations                        │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐ ┌───────────┐ │
│  │    MinIO    │ │   Qdrant    │ │   MongoDB   │ │  OpenAI   │ │
│  │     S3      │ │   Pinecone  │ │  Postgres   │ │  Gemini   │ │
│  │    GCS      │ │   Weaviate  │ │             │ │  Claude   │ │
│  └─────────────┘ └─────────────┘ └─────────────┘ └───────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

---

## Storage Services

### Blob Storage

Stores binary artifacts: videos, audio, frames, JSON files.

#### Abstract Interface

```python
from abc import ABC, abstractmethod
from typing import BinaryIO, AsyncIterator
from dataclasses import dataclass


@dataclass
class BlobMetadata:
    path: str
    size_bytes: int
    content_type: str
    created_at: datetime
    etag: str


class BlobStorageBase(ABC):
    """Abstract base class for blob storage operations."""

    @abstractmethod
    async def upload(
        self,
        bucket: str,
        path: str,
        data: BinaryIO | bytes,
        content_type: str = "application/octet-stream",
        metadata: dict[str, str] | None = None
    ) -> BlobMetadata:
        """Upload a blob to storage."""
        pass

    @abstractmethod
    async def download(self, bucket: str, path: str) -> bytes:
        """Download a blob from storage."""
        pass

    @abstractmethod
    async def download_stream(
        self, bucket: str, path: str
    ) -> AsyncIterator[bytes]:
        """Stream download a blob in chunks."""
        pass

    @abstractmethod
    async def delete(self, bucket: str, path: str) -> bool:
        """Delete a blob from storage."""
        pass

    @abstractmethod
    async def exists(self, bucket: str, path: str) -> bool:
        """Check if a blob exists."""
        pass

    @abstractmethod
    async def get_metadata(self, bucket: str, path: str) -> BlobMetadata:
        """Get blob metadata without downloading."""
        pass

    @abstractmethod
    async def generate_presigned_url(
        self,
        bucket: str,
        path: str,
        expiry_seconds: int = 3600,
        method: str = "GET"
    ) -> str:
        """Generate a presigned URL for direct access."""
        pass

    @abstractmethod
    async def list_blobs(
        self,
        bucket: str,
        prefix: str = "",
        max_results: int = 1000
    ) -> list[BlobMetadata]:
        """List blobs with optional prefix filter."""
        pass
```

#### Bucket Structure

```
videos/
├── {video_id}/
│   ├── original.mp4           # Original downloaded video
│   ├── audio.mp3              # Extracted audio
│   └── metadata.json          # YouTube metadata

chunks/
├── {video_id}/
│   ├── transcripts/
│   │   ├── chunk_{id}.json    # Detailed transcript with word timestamps
│   │   └── ...
│   ├── audio/
│   │   ├── chunk_{id}.mp3     # Audio segment
│   │   └── ...
│   └── video/
│       ├── chunk_{id}.mp4     # Video segment
│       └── ...

frames/
├── {video_id}/
│   ├── full/
│   │   ├── frame_{number}.jpg # Full resolution frame
│   │   └── ...
│   └── thumbnails/
│       ├── frame_{number}.jpg # Thumbnail
│       └── ...
```

#### Provider Implementations

| Provider | Use Case | Configuration |
|----------|----------|---------------|
| **MinIO** | Local development, self-hosted | `provider: minio` |
| **AWS S3** | Production (AWS) | `provider: s3` |
| **Google Cloud Storage** | Production (GCP) | `provider: gcs` |
| **Azure Blob** | Production (Azure) | `provider: azure` |

---

### Vector Database

Stores and searches embedding vectors for semantic retrieval.

#### Abstract Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SearchResult:
    id: str
    score: float
    payload: dict


@dataclass
class VectorPoint:
    id: str
    vector: list[float]
    payload: dict


class VectorDBBase(ABC):
    """Abstract base class for vector database operations."""

    @abstractmethod
    async def create_collection(
        self,
        name: str,
        vector_size: int,
        distance_metric: str = "cosine"
    ) -> bool:
        """Create a new collection/index."""
        pass

    @abstractmethod
    async def delete_collection(self, name: str) -> bool:
        """Delete a collection."""
        pass

    @abstractmethod
    async def collection_exists(self, name: str) -> bool:
        """Check if collection exists."""
        pass

    @abstractmethod
    async def upsert(
        self,
        collection: str,
        points: list[VectorPoint]
    ) -> int:
        """Insert or update vectors. Returns count of upserted points."""
        pass

    @abstractmethod
    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 10,
        filters: dict | None = None,
        score_threshold: float | None = None
    ) -> list[SearchResult]:
        """Search for similar vectors."""
        pass

    @abstractmethod
    async def delete_by_filter(
        self,
        collection: str,
        filters: dict
    ) -> int:
        """Delete vectors matching filter. Returns count deleted."""
        pass

    @abstractmethod
    async def get_by_ids(
        self,
        collection: str,
        ids: list[str]
    ) -> list[VectorPoint]:
        """Retrieve vectors by ID."""
        pass
```

#### Collection Schema

```python
# Transcript embeddings collection
{
    "name": "transcript_embeddings",
    "vector_size": 1536,  # OpenAI text-embedding-3-small
    "distance_metric": "cosine",
    "payload_schema": {
        "video_id": "string",
        "chunk_id": "string",
        "start_time": "float",
        "end_time": "float",
        "text_preview": "string",
        "language": "string"
    }
}

# Frame embeddings collection
{
    "name": "frame_embeddings",
    "vector_size": 512,  # CLIP ViT-B/32
    "distance_metric": "cosine",
    "payload_schema": {
        "video_id": "string",
        "chunk_id": "string",
        "timestamp": "float",
        "frame_number": "integer",
        "description": "string"
    }
}

# Video chunk embeddings (via description text)
{
    "name": "video_embeddings",
    "vector_size": 1536,
    "distance_metric": "cosine",
    "payload_schema": {
        "video_id": "string",
        "chunk_id": "string",
        "start_time": "float",
        "end_time": "float",
        "description": "string"
    }
}
```

#### Provider Implementations

| Provider | Use Case | Configuration |
|----------|----------|---------------|
| **Qdrant** | Default, self-hosted or cloud | `provider: qdrant` |
| **Pinecone** | Managed, serverless | `provider: pinecone` |
| **Weaviate** | Self-hosted, hybrid search | `provider: weaviate` |
| **Milvus** | Large scale, self-hosted | `provider: milvus` |

---

### Document Database

Stores structured metadata: videos, chunks, citations.

#### Abstract Interface

```python
from abc import ABC, abstractmethod
from typing import TypeVar, Generic

T = TypeVar('T')


class DocumentDBBase(ABC, Generic[T]):
    """Abstract base class for document database operations."""

    @abstractmethod
    async def insert(self, collection: str, document: T) -> str:
        """Insert a document. Returns document ID."""
        pass

    @abstractmethod
    async def insert_many(self, collection: str, documents: list[T]) -> list[str]:
        """Insert multiple documents. Returns list of IDs."""
        pass

    @abstractmethod
    async def find_by_id(self, collection: str, id: str) -> T | None:
        """Find a document by ID."""
        pass

    @abstractmethod
    async def find(
        self,
        collection: str,
        filters: dict,
        skip: int = 0,
        limit: int = 100,
        sort: list[tuple[str, int]] | None = None
    ) -> list[T]:
        """Find documents matching filters."""
        pass

    @abstractmethod
    async def find_one(self, collection: str, filters: dict) -> T | None:
        """Find a single document matching filters."""
        pass

    @abstractmethod
    async def update(
        self,
        collection: str,
        id: str,
        updates: dict
    ) -> bool:
        """Update a document. Returns True if updated."""
        pass

    @abstractmethod
    async def update_many(
        self,
        collection: str,
        filters: dict,
        updates: dict
    ) -> int:
        """Update multiple documents. Returns count updated."""
        pass

    @abstractmethod
    async def delete(self, collection: str, id: str) -> bool:
        """Delete a document. Returns True if deleted."""
        pass

    @abstractmethod
    async def delete_many(self, collection: str, filters: dict) -> int:
        """Delete multiple documents. Returns count deleted."""
        pass

    @abstractmethod
    async def count(self, collection: str, filters: dict | None = None) -> int:
        """Count documents matching filters."""
        pass
```

#### Collections

```
database: youtube_rag
├── videos              # VideoMetadata documents
├── transcript_chunks   # TranscriptChunk documents
├── frame_chunks        # FrameChunk documents
├── audio_chunks        # AudioChunk documents
├── video_chunks        # VideoChunk documents
└── citations           # Cached SourceCitation documents
```

#### Provider Implementations

| Provider | Use Case | Configuration |
|----------|----------|---------------|
| **MongoDB** | Default, flexible schema | `provider: mongodb` |
| **PostgreSQL + JSONB** | SQL preferred, ACID | `provider: postgres` |

---

## AI/ML Services

### Transcription Service

Converts audio to text with word-level timestamps.

#### Abstract Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class TranscriptionWord:
    word: str
    start_time: float
    end_time: float
    confidence: float


@dataclass
class TranscriptionSegment:
    text: str
    start_time: float
    end_time: float
    words: list[TranscriptionWord]
    language: str
    confidence: float


@dataclass
class TranscriptionResult:
    segments: list[TranscriptionSegment]
    full_text: str
    language: str
    duration_seconds: float


class TranscriptionServiceBase(ABC):
    """Abstract base class for transcription services."""

    @abstractmethod
    async def transcribe(
        self,
        audio_path: str,
        language_hint: str | None = None,
        word_timestamps: bool = True
    ) -> TranscriptionResult:
        """Transcribe audio file to text."""
        pass

    @abstractmethod
    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language_hint: str | None = None
    ) -> AsyncIterator[TranscriptionSegment]:
        """Transcribe streaming audio."""
        pass

    @abstractmethod
    def supported_languages(self) -> list[str]:
        """Return list of supported language codes."""
        pass
```

#### Provider Implementations

| Provider | Use Case | Configuration |
|----------|----------|---------------|
| **OpenAI Whisper API** | Cloud, high accuracy | `provider: openai_whisper` |
| **Deepgram** | Cloud, fast, streaming | `provider: deepgram` |
| **AssemblyAI** | Cloud, speaker diarization | `provider: assemblyai` |
| **Azure Speech** | Cloud, enterprise | `provider: azure_speech` |
| **Google Speech-to-Text** | Cloud, streaming | `provider: google_speech` |

---

### Embedding Service

Generates vector embeddings for text and images.

#### Abstract Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class EmbeddingModality(str, Enum):
    TEXT = "text"
    IMAGE = "image"


@dataclass
class EmbeddingResult:
    vector: list[float]
    dimensions: int
    model: str
    modality: EmbeddingModality
    tokens_used: int | None = None


class EmbeddingServiceBase(ABC):
    """Abstract base class for embedding generation."""

    @abstractmethod
    async def embed_text(
        self,
        text: str,
        model: str | None = None
    ) -> EmbeddingResult:
        """Generate embedding for text."""
        pass

    @abstractmethod
    async def embed_texts(
        self,
        texts: list[str],
        model: str | None = None
    ) -> list[EmbeddingResult]:
        """Generate embeddings for multiple texts (batched)."""
        pass

    @abstractmethod
    async def embed_image(
        self,
        image_path: str,
        model: str | None = None
    ) -> EmbeddingResult:
        """Generate embedding for an image."""
        pass

    @abstractmethod
    async def embed_images(
        self,
        image_paths: list[str],
        model: str | None = None
    ) -> list[EmbeddingResult]:
        """Generate embeddings for multiple images (batched)."""
        pass

    @property
    @abstractmethod
    def text_dimensions(self) -> int:
        """Return dimensions of text embeddings."""
        pass

    @property
    @abstractmethod
    def image_dimensions(self) -> int:
        """Return dimensions of image embeddings."""
        pass
```

#### Provider Implementations

| Provider | Modalities | Configuration |
|----------|------------|---------------|
| **OpenAI** | Text | `text_provider: openai` |
| **Azure OpenAI** | Text | `text_provider: azure_openai` |
| **Cohere** | Text | `text_provider: cohere` |
| **Voyage AI** | Text | `text_provider: voyage` |
| **OpenAI CLIP** | Image | `image_provider: clip` |
| **Google Vertex AI** | Text, Image | `provider: vertex` |

---

### LLM Service

Generates answers and reasoning for queries.

#### Abstract Interface

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    role: MessageRole
    content: str
    images: list[str] | None = None  # Base64 or URLs
    videos: list[str] | None = None  # Base64 or URLs (for multimodal)


@dataclass
class LLMResponse:
    content: str
    finish_reason: str
    usage: dict[str, int]
    model: str


class LLMServiceBase(ABC):
    """Abstract base class for LLM services."""

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_mode: bool = False
    ) -> LLMResponse:
        """Generate a completion."""
        pass

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024
    ) -> AsyncIterator[str]:
        """Generate a streaming completion."""
        pass

    @property
    @abstractmethod
    def supports_vision(self) -> bool:
        """Whether this model supports image input."""
        pass

    @property
    @abstractmethod
    def supports_video(self) -> bool:
        """Whether this model supports video input."""
        pass

    @property
    @abstractmethod
    def context_window(self) -> int:
        """Maximum context window in tokens."""
        pass
```

#### Provider Implementations

| Provider | Models | Vision | Video | Configuration |
|----------|--------|--------|-------|---------------|
| **OpenAI** | GPT-4o, GPT-4-turbo | Yes | No | `provider: openai` |
| **Anthropic** | Claude 3.5 Sonnet | Yes | No* | `provider: anthropic` |
| **Google** | Gemini 1.5 Pro/Flash | Yes | Yes | `provider: google` |
| **Azure OpenAI** | GPT-4o, GPT-4 | Yes | No | `provider: azure_openai` |

*Video support may be added in future versions

---

### YouTube Downloader

Downloads videos and metadata from YouTube.

#### Interface

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass
class YouTubeMetadata:
    id: str
    title: str
    description: str
    duration_seconds: int
    channel_name: str
    channel_id: str
    upload_date: datetime
    thumbnail_url: str
    view_count: int
    like_count: int | None
    tags: list[str]
    categories: list[str]


@dataclass
class DownloadResult:
    video_path: Path
    audio_path: Path
    metadata: YouTubeMetadata
    format_info: dict


class YouTubeDownloader:
    """Downloads videos from YouTube using yt-dlp."""

    async def download(
        self,
        url: str,
        output_dir: Path,
        video_format: str = "mp4",
        audio_format: str = "mp3",
        max_resolution: int = 1080
    ) -> DownloadResult:
        """Download video and extract audio."""
        pass

    async def get_metadata(self, url: str) -> YouTubeMetadata:
        """Get video metadata without downloading."""
        pass

    async def get_subtitles(
        self,
        url: str,
        languages: list[str] = ["en"]
    ) -> dict[str, str]:
        """Get available subtitles/captions."""
        pass

    def validate_url(self, url: str) -> bool:
        """Validate YouTube URL format."""
        pass

    def extract_video_id(self, url: str) -> str:
        """Extract video ID from URL."""
        pass
```

**Implementation**: Uses `yt-dlp` library for robust YouTube downloading.

---

## Video Processing

### Frame Extractor

Extracts frames from video at specified intervals.

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractedFrame:
    path: Path
    thumbnail_path: Path
    frame_number: int
    timestamp: float
    width: int
    height: int


class FrameExtractor:
    """Extracts frames from video files."""

    async def extract_frames(
        self,
        video_path: Path,
        output_dir: Path,
        interval_seconds: float = 2.0,
        format: str = "jpg",
        quality: int = 85,
        max_dimension: int = 1920,
        thumbnail_size: tuple[int, int] = (320, 180)
    ) -> list[ExtractedFrame]:
        """Extract frames at regular intervals."""
        pass

    async def extract_frame_at(
        self,
        video_path: Path,
        timestamp: float,
        output_path: Path
    ) -> ExtractedFrame:
        """Extract a single frame at specific timestamp."""
        pass
```

**Implementation**: Uses `ffmpeg` via `ffmpeg-python` or `moviepy`.

---

### Video Chunker

Splits video into segments for multimodal LLM input.

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VideoSegment:
    path: Path
    start_time: float
    end_time: float
    duration: float
    size_bytes: int
    has_audio: bool


class VideoChunker:
    """Splits videos into chunks for multimodal processing."""

    async def chunk_video(
        self,
        video_path: Path,
        output_dir: Path,
        chunk_seconds: int = 30,
        overlap_seconds: int = 2,
        max_size_mb: float = 20.0,
        format: str = "mp4",
        include_audio: bool = True
    ) -> list[VideoSegment]:
        """Split video into chunks."""
        pass

    async def get_video_info(self, video_path: Path) -> dict:
        """Get video metadata (duration, resolution, fps, etc.)."""
        pass
```

**Implementation**: Uses `ffmpeg` for efficient video splitting.

---

## Infrastructure Factory

The factory pattern creates infrastructure instances based on configuration.

```python
from typing import Type


class InfrastructureFactory:
    """Factory for creating infrastructure service instances."""

    _blob_providers: dict[str, Type[BlobStorageBase]] = {
        "minio": MinIOBlobStorage,
        "s3": S3BlobStorage,
        "gcs": GCSBlobStorage,
    }

    _vector_providers: dict[str, Type[VectorDBBase]] = {
        "qdrant": QdrantVectorDB,
        "pinecone": PineconeVectorDB,
    }

    _document_providers: dict[str, Type[DocumentDBBase]] = {
        "mongodb": MongoDBDocumentDB,
        "postgres": PostgresDocumentDB,
    }

    _transcription_providers: dict[str, Type[TranscriptionServiceBase]] = {
        "openai_whisper": OpenAIWhisperService,
        "deepgram": DeepgramService,
        "assemblyai": AssemblyAIService,
    }

    _llm_providers: dict[str, Type[LLMServiceBase]] = {
        "openai": OpenAILLMService,
        "anthropic": AnthropicLLMService,
        "google": GoogleLLMService,
    }

    @classmethod
    def create_blob_storage(cls, config: BlobStorageConfig) -> BlobStorageBase:
        provider_class = cls._blob_providers.get(config.provider)
        if not provider_class:
            raise ValueError(f"Unknown blob provider: {config.provider}")
        return provider_class(config)

    # Similar methods for other services...
```

---

## Local Development Setup

### Docker Compose Services

```yaml
version: '3.8'

services:
  minio:
    image: minio/minio:latest
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    command: server /data --console-address ":9001"
    volumes:
      - minio_data:/data

  qdrant:
    image: qdrant/qdrant:latest
    ports:
      - "6333:6333"
      - "6334:6334"
    volumes:
      - qdrant_data:/qdrant/storage

  mongodb:
    image: mongo:7
    ports:
      - "27017:27017"
    environment:
      MONGO_INITDB_ROOT_USERNAME: admin
      MONGO_INITDB_ROOT_PASSWORD: changeme
    volumes:
      - mongo_data:/data/db

volumes:
  minio_data:
  qdrant_data:
  mongo_data:
```

---

## Health Checks

Each infrastructure service implements health checking:

```python
class HealthCheckable(ABC):
    """Mixin for services that support health checks."""

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Check service health."""
        pass


@dataclass
class HealthStatus:
    healthy: bool
    latency_ms: float
    message: str | None = None
    details: dict | None = None
```

Aggregated health endpoint:

```http
GET /health

{
  "status": "ok",
  "healthy": true,
  "readiness": true,
  "liveness": true,
  "latency_ms": 7.4,
  "summary": {
    "total": 4,
    "healthy": 4,
    "unhealthy": 0
  },
  "checks": {
    "multi_bucket": {
      "healthy": true,
      "latency_ms": 2.1,
      "message": "all buckets reachable"
    },
    "qdrant": {
      "healthy": true,
      "latency_ms": 1.7,
      "message": "qdrant is healthy"
    },
    "mongodb": {
      "healthy": true,
      "latency_ms": 3.2,
      "message": "mongodb ping ok"
    },
    "otel": {
      "healthy": true,
      "latency_ms": 0.4,
      "message": "OpenTelemetry providers are active"
    }
  }
}
```

`GET /health/ready` uses the same payload contract and returns `503` when
`readiness=false`. This readiness probe excludes optional observability checks.
