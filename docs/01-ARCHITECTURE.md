# Architecture

## System Overview

The YouTube RAG Server follows a **layered architecture** with clear separation of concerns, designed for testability, extensibility, and cloud-native deployment.

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                         CONSUMERS                                │
│              (Semantic Kernel / Agent Framework)                 │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      EXPOSURE LAYER                              │
│         ┌─────────────────┬─────────────────┐                   │
│         │   MCP Server    │  OpenAPI Plugin │                   │
│         └─────────────────┴─────────────────┘                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      APPLICATION LAYER                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │ Ingestion    │ │   Query      │ │   Source Retrieval       │ │
│  │ Service      │ │   Service    │ │   Service                │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                       DOMAIN LAYER                               │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌──────────────┐  │
│  │   Video    │ │   Chunk    │ │ Embedding  │ │    Source    │  │
│  │  Metadata  │ │  (multi)   │ │   Index    │ │   Citation   │  │
│  └────────────┘ └────────────┘ └────────────┘ └──────────────┘  │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                   INFRASTRUCTURE LAYER                           │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │ Blob Storage │ │  Vector DB   │ │      Document DB         │ │
│  │   (MinIO)    │ │  (Qdrant)    │ │      (MongoDB)           │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │  YouTube     │ │ Transcription│ │     Embedding            │ │
│  │  Downloader  │ │   Service    │ │     Provider             │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
│  ┌──────────────┐                                               │
│  │     LLM      │                                               │
│  │   Provider   │                                               │
│  └──────────────┘                                               │
└─────────────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      COMMONS PACKAGE                             │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────────────────┐ │
│  │   Settings   │ │  Telemetry   │ │   Infrastructure         │ │
│  │   Loader     │ │   (→ Loki)   │ │   Factories              │ │
│  └──────────────┘ └──────────────┘ └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

## Layer Descriptions

### 1. Exposure Layer

The topmost layer that exposes the system's capabilities to external consumers.

#### MCP Server
- Implements the Model Context Protocol for AI agent integration
- Exposes tools that agents can discover and invoke
- Handles MCP-specific protocol concerns (capability negotiation, tool schemas)

#### OpenAPI Plugin
- RESTful API for direct HTTP integration
- OpenAPI 3.0 specification for documentation and client generation
- Can be used as a ChatGPT/Copilot plugin

### 2. Application Layer

Contains the business logic orchestration without knowing about external protocols.

#### Ingestion Service
- Orchestrates the full video ingestion pipeline
- Coordinates download → transcription → frame extraction → embedding
- Manages video status transitions
- Handles failures and retries

#### Query Service
- Processes semantic queries against indexed videos
- Coordinates embedding generation → vector search → context retrieval → LLM generation
- Builds citation metadata for responses

#### Source Retrieval Service
- Generates presigned URLs for source artifacts
- Handles multimodal source access (transcript segments, frames, audio clips)
- Manages citation resolution

### 3. Domain Layer

Pure business entities and logic, free from infrastructure concerns.

#### Video Metadata
- Core entity representing an indexed YouTube video
- Lifecycle management (pending → processing → ready → failed)

#### Chunk (Multimodal)
- Represents indexed segments of content
- Variants: TranscriptChunk, FrameChunk, AudioChunk
- Each chunk has temporal positioning (start_time, end_time)

#### Embedding Index
- Represents vector embeddings for semantic search
- Links back to source chunks

#### Source Citation
- Represents a citable source in a query response
- Contains temporal range and access URLs

### 4. Infrastructure Layer

Concrete implementations of external services and storage.

#### Storage
- **Blob Storage**: Raw video files, audio, frames, JSON artifacts
- **Vector DB**: Embedding vectors for semantic search
- **Document DB**: Metadata, chunks, citations

#### External Services
- **YouTube Downloader**: yt-dlp wrapper for video acquisition
- **Transcription Service**: Speech-to-text (cloud provider TBD)
- **Embedding Provider**: Text and image embeddings (cloud provider TBD)
- **LLM Provider**: Query answering and reasoning (cloud provider TBD)

### 5. Commons Package

Shared utilities designed for potential extraction to a separate repository.

#### Settings Loader
- Hierarchical configuration loading (appsettings.json + env vars + secrets)
- Environment-aware (dev/staging/prod)
- Pydantic-based validation

#### Telemetry
- Structured logging with correlation IDs
- Decorators for tracing and exception logging
- Loki-compatible output format

#### Infrastructure Factories
- Abstract base classes for all infrastructure components
- Factory pattern for provider instantiation based on configuration

## Package Structure

```
youtube-rag-server/
├── pyproject.toml
├── poetry.lock
├── Dockerfile
├── docker-compose.yml              # Local dev with MinIO, Qdrant, MongoDB
├── k8s/                            # Manifests for ArgoCD
│   ├── base/
│   └── overlays/
│       ├── dev/
│       ├── staging/
│       └── prod/
│
├── config/
│   ├── appsettings.json            # Defaults
│   ├── appsettings.dev.json
│   ├── appsettings.staging.json
│   └── appsettings.prod.json
│
├── src/
│   ├── commons/                    # Shared package
│   │   ├── __init__.py
│   │   ├── settings/
│   │   │   ├── __init__.py
│   │   │   ├── loader.py           # Loads appsettings + env vars
│   │   │   └── models.py           # Pydantic settings models
│   │   ├── telemetry/
│   │   │   ├── __init__.py
│   │   │   ├── logger.py           # Structured logging → Loki
│   │   │   └── decorators.py       # @trace, @log_exceptions
│   │   └── infrastructure/
│   │       ├── __init__.py
│   │       ├── blob/
│   │       │   ├── base.py         # ABC
│   │       │   └── minio.py        # MinIO implementation
│   │       ├── vectordb/
│   │       │   ├── base.py         # ABC
│   │       │   └── qdrant.py       # Qdrant implementation
│   │       └── documentdb/
│   │           ├── base.py         # ABC
│   │           └── mongodb.py      # MongoDB implementation
│   │
│   ├── domain/
│   │   ├── __init__.py
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   ├── video.py            # VideoMetadata, VideoStatus
│   │   │   ├── chunk.py            # TranscriptChunk, FrameChunk, AudioChunk
│   │   │   ├── embedding.py        # EmbeddingVector, EmbeddingIndex
│   │   │   └── citation.py         # SourceCitation, TimestampRange
│   │   └── exceptions.py           # Domain-specific exceptions
│   │
│   ├── application/
│   │   ├── __init__.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── ingestion.py        # IngestionService
│   │   │   ├── query.py            # QueryService
│   │   │   └── source_retrieval.py # SourceRetrievalService
│   │   ├── pipelines/
│   │   │   ├── __init__.py
│   │   │   ├── download.py         # YouTubeDownloadPipeline
│   │   │   ├── transcription.py    # TranscriptionPipeline
│   │   │   ├── frame_extraction.py # FrameExtractionPipeline
│   │   │   └── embedding.py        # EmbeddingPipeline
│   │   └── dtos/
│   │       ├── __init__.py
│   │       ├── requests.py
│   │       └── responses.py
│   │
│   ├── infrastructure/
│   │   ├── __init__.py
│   │   ├── youtube/
│   │   │   ├── __init__.py
│   │   │   └── downloader.py       # yt-dlp wrapper
│   │   ├── transcription/
│   │   │   ├── __init__.py
│   │   │   ├── base.py             # ABC
│   │   │   └── cloud.py            # Cloud transcription service
│   │   ├── embeddings/
│   │   │   ├── __init__.py
│   │   │   ├── base.py             # ABC
│   │   │   ├── text.py             # Text embedding provider
│   │   │   └── image.py            # Image embedding provider
│   │   └── llm/
│   │       ├── __init__.py
│   │       ├── base.py             # ABC
│   │       └── cloud.py            # Cloud LLM provider
│   │
│   └── api/
│       ├── __init__.py
│       ├── main.py                 # FastAPI app factory
│       ├── dependencies.py         # DI container
│       ├── middleware/
│       │   ├── __init__.py
│       │   ├── logging.py
│       │   └── error_handler.py
│       ├── mcp/
│       │   ├── __init__.py
│       │   └── server.py           # MCP protocol implementation
│       └── openapi/
│           ├── __init__.py
│           └── routes/
│               ├── __init__.py
│               ├── ingestion.py    # POST /videos/ingest
│               ├── query.py        # POST /videos/{id}/query
│               └── sources.py      # GET /videos/{id}/sources
│
└── tests/
    ├── __init__.py
    ├── conftest.py                 # Shared fixtures
    ├── unit/
    │   ├── domain/
    │   ├── application/
    │   └── infrastructure/
    ├── integration/
    │   ├── test_ingestion_flow.py
    │   └── test_query_flow.py
    └── e2e/
        └── test_mcp_protocol.py
```

## Design Principles

### 1. Dependency Inversion
- All infrastructure components implement abstract base classes
- Application layer depends on abstractions, not implementations
- Enables easy testing with mocks and provider swapping

### 2. Hexagonal Architecture (Ports & Adapters)
- Domain and Application layers are the "core"
- Infrastructure and API layers are "adapters"
- Core has no knowledge of how it's exposed or what stores data

### 3. Cloud-Native by Design
- Stateless application containers
- External state in managed services
- Configuration via environment
- Horizontal scalability

### 4. Multimodal First
- All data structures support multiple modalities
- Unified chunk abstraction with modality-specific variants
- Consistent temporal positioning across modalities

## Data Flow

### Ingestion Flow

```
User → ingest_video(url)
  → YouTubeDownloader.download()
    → [video.mp4, audio.mp3, metadata.json] → Blob Storage
  → TranscriptionPipeline.process(audio)
    → [TranscriptChunk[]] → MongoDB + Blob Storage
  → FrameExtractionPipeline.process(video)
    → [FrameChunk[]] → MongoDB + Blob Storage
  → EmbeddingPipeline.process(transcripts, frames)
    → [EmbeddingVector[]] → Qdrant
  → Update VideoMetadata.status = ready
```

### Query Flow

```
User → query_video(video_id, "What does he say at minute 5?")
  → EmbeddingProvider.embed(query)
  → Qdrant.search(query_embedding, video_id)
    → [relevant_chunk_ids]
  → MongoDB.get_chunks(chunk_ids)
    → [TranscriptChunk[], FrameChunk[]]
  → LLM.generate_answer(query, chunks)
    → {answer, reasoning, citations}
  → Build SourceCitations with presigned URLs
  → Return QueryResponse
```

## Error Handling Strategy

### Ingestion Errors
- Video download failures: Retry with exponential backoff, mark as failed after max retries
- Transcription failures: Partial success allowed (video still queryable without transcript)
- Embedding failures: Retry individually, track failed chunks

### Query Errors
- Vector search failures: Return error with retry suggestion
- LLM failures: Fallback to returning raw relevant chunks
- Source access failures: Return available sources, note unavailable ones

## Scalability Considerations

### Ingestion
- Long-running process, consider background job queue (future enhancement)
- Large videos may need streaming processing
- Frame extraction is CPU-intensive, consider worker pools

### Query
- Stateless, horizontally scalable
- Qdrant handles vector search scaling
- Cache frequently accessed video metadata

## Security Considerations

- No direct YouTube URL exposure to end users
- Presigned URLs with expiration for blob access
- Input validation on all user-provided data
- Rate limiting on ingestion endpoints
- Authentication/authorization (future enhancement)
