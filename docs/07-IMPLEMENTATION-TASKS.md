# Implementation Tasks

## Overview

This document breaks down the implementation into phases with specific tasks. Each phase builds upon the previous one, enabling incremental development and testing.

---

## Phase 0: Project Setup ✅

**Goal**: Initialize the project with all tooling and base structure.

**Status**: COMPLETED

### Tasks

- [x] **0.1** Initialize project with Python 3.11+ (using uv)

- [x] **0.2** Configure development tools
  - [x] Add `ruff` for linting
  - [x] Add `mypy` for type checking
  - [x] Add `pytest`, `pytest-cov`, `pytest-asyncio` for testing
  - [x] Create `pyproject.toml` with tool configurations

- [x] **0.3** Create directory structure
  ```
  src/
  ├── commons/
  ├── domain/
  ├── application/
  ├── infrastructure/
  └── api/
  tests/
  ├── unit/
  ├── integration/
  └── e2e/
  config/
  ```

- [x] **0.4** Set up pre-commit hooks
  - [x] Ruff linting
  - [x] Mypy type checking
  - [x] Conventional commits

- [x] **0.5** Create base configuration files
  - [x] `config/appsettings.json`
  - [x] `config/appsettings.dev.json`
  - [x] `.env.example`

- [x] **0.6** Set up Docker environment
  - [x] Create `Dockerfile`
  - [x] Create `docker-compose.yml` with MinIO, Qdrant, MongoDB

- [x] **0.7** Initialize Git repository
  - [x] Create `.gitignore`
  - [x] Initial commit

---

## Phase 1: Commons Package ✅

**Goal**: Build the shared utilities that all other layers depend on.

**Status**: COMPLETED

### Tasks

#### 1.1 Settings System

- [x] **1.1.1** Create Pydantic settings models
  - [x] `src/commons/settings/models.py`
  - [x] All settings classes from 05-CONFIGURATION.md

- [x] **1.1.2** Implement settings loader
  - [x] `src/commons/settings/loader.py`
  - [x] JSON file loading
  - [x] Environment variable merging
  - [x] Environment-specific overrides

- [x] **1.1.3** Write unit tests for settings
  - [x] Test default values
  - [x] Test environment override
  - [x] Test validation

#### 1.2 Telemetry

- [x] **1.2.1** Create structured logger
  - [x] `src/commons/telemetry/logger.py`
  - [x] JSON formatted output
  - [x] Correlation ID support
  - [x] Context management

- [x] **1.2.2** Create decorators
  - [x] `src/commons/telemetry/decorators.py`
  - [x] `@trace` for function tracing
  - [x] `@log_exceptions` for error logging
  - [x] `@timed` for performance metrics

- [x] **1.2.3** Write unit tests for telemetry

#### 1.3 Infrastructure Base Classes

- [x] **1.3.1** Create blob storage ABC
  - [x] `src/commons/infrastructure/blob/base.py`
  - [x] All methods from 04-INFRASTRUCTURE.md

- [x] **1.3.2** Create vector DB ABC
  - [x] `src/commons/infrastructure/vectordb/base.py`

- [x] **1.3.3** Create document DB ABC
  - [x] `src/commons/infrastructure/documentdb/base.py`

---

## Phase 2: Domain Layer ✅

**Goal**: Implement all domain models and business logic.

**Status**: COMPLETED

### Tasks

#### 2.1 Core Models

- [x] **2.1.1** Implement VideoMetadata
  - [x] `src/domain/models/video.py`
  - [x] `VideoStatus` enum
  - [x] `VideoMetadata` model
  - [x] Validation logic

- [x] **2.1.2** Implement Chunk models
  - [x] `src/domain/models/chunk.py`
  - [x] `Modality` enum
  - [x] `BaseChunk` abstract class
  - [x] `TranscriptChunk` with word timestamps
  - [x] `FrameChunk` with image metadata
  - [x] `AudioChunk` with audio metadata
  - [x] `VideoChunk` with video segment metadata

- [x] **2.1.3** Implement Embedding models
  - [x] `src/domain/models/embedding.py`
  - [x] `EmbeddingVector` model

- [x] **2.1.4** Implement Citation models
  - [x] `src/domain/models/citation.py`
  - [x] `TimestampRange` value object
  - [x] `SourceCitation` model

#### 2.2 Value Objects

- [x] **2.2.1** Implement YouTubeVideoId
  - [x] URL parsing
  - [x] Validation
  - [x] URL generation

- [x] **2.2.2** Implement ChunkingConfig
  - [x] All chunking parameters

#### 2.3 Domain Exceptions

- [x] **2.3.1** Create exception hierarchy
  - [x] `src/domain/exceptions.py`
  - [x] All exceptions from 02-DOMAIN-MODELS.md

#### 2.4 Domain Tests

- [x] **2.4.1** Unit tests for all models
- [x] **2.4.2** Unit tests for value objects
- [x] **2.4.3** Unit tests for URL parsing

---

## Phase 3: Infrastructure Layer ✅

**Goal**: Implement concrete infrastructure providers.

**Status**: COMPLETED (tests pending)

### Tasks

#### 3.1 Blob Storage

- [x] **3.1.1** Implement MinIO provider
  - [x] `src/commons/infrastructure/blob/minio_provider.py`
  - [x] All CRUD operations
  - [x] Presigned URL generation

- [ ] **3.1.2** Integration tests with testcontainers
  - [ ] Upload/download tests
  - [ ] Presigned URL tests

#### 3.2 Vector Database

- [x] **3.2.1** Implement Qdrant provider
  - [x] `src/commons/infrastructure/vectordb/qdrant_provider.py`
  - [x] Collection management
  - [x] Vector upsert/search
  - [x] Filtering

- [ ] **3.2.2** Integration tests with testcontainers

#### 3.3 Document Database

- [x] **3.3.1** Implement MongoDB provider
  - [x] `src/commons/infrastructure/documentdb/mongodb_provider.py`
  - [x] CRUD operations
  - [x] Query building

- [ ] **3.3.2** Integration tests with testcontainers

#### 3.4 YouTube Downloader

- [x] **3.4.1** Implement yt-dlp wrapper
  - [x] `src/infrastructure/youtube/downloader.py`
  - [x] Video download
  - [x] Audio extraction
  - [x] Metadata fetching

- [ ] **3.4.2** Unit tests with mocked responses

#### 3.5 AI Services (Abstract + One Provider Each)

- [x] **3.5.1** Transcription service
  - [x] `src/infrastructure/transcription/base.py`
  - [x] `src/infrastructure/transcription/openai_whisper.py`

- [x] **3.5.2** Embedding service
  - [x] `src/infrastructure/embeddings/base.py`
  - [x] `src/infrastructure/embeddings/openai_embeddings.py` (text)
  - [x] `src/infrastructure/embeddings/clip_embeddings.py` (image)

- [x] **3.5.3** LLM service
  - [x] `src/infrastructure/llm/base.py`
  - [x] `src/infrastructure/llm/openai_llm.py`

#### 3.6 Video Processing

- [x] **3.6.1** Frame extractor
  - [x] `src/infrastructure/video/ffmpeg_extractor.py`
  - [x] FFmpeg integration
  - [x] Thumbnail generation

- [x] **3.6.2** Video chunker
  - [x] `src/infrastructure/video/ffmpeg_chunker.py`
  - [x] Segment splitting
  - [x] Size management

#### 3.7 Infrastructure Factory

- [x] **3.7.1** Implement factory pattern
  - [x] `src/infrastructure/factory.py`
  - [x] Provider registration
  - [x] Configuration-based instantiation

---

## Phase 4: Application Layer 🔄

**Goal**: Implement business logic orchestration.

**Status**: IN PROGRESS

### Tasks

#### 4.1 DTOs

- [x] **4.1.1** Create ingestion DTOs
  - [x] `src/application/dtos/ingestion.py`
  - [x] `IngestVideoRequest`
  - [x] `IngestVideoResponse`
  - [x] `IngestionStatusResponse`

- [ ] **4.1.2** Create query DTOs
  - [ ] `src/application/dtos/query.py`
  - [ ] `QueryVideoRequest`
  - [ ] `QueryVideoResponse`

- [ ] **4.1.3** Create sources DTOs
  - [ ] `src/application/dtos/sources.py`
  - [ ] `GetSourcesRequest`
  - [ ] `SourcesResponse`

#### 4.2 Pipelines

- [ ] **4.2.1** Download pipeline
  - [ ] `src/application/pipelines/download.py`
  - [ ] YouTube download orchestration
  - [ ] Blob storage upload
  - [ ] Metadata extraction

- [ ] **4.2.2** Transcription pipeline
  - [ ] `src/application/pipelines/transcription.py`
  - [ ] Audio processing
  - [ ] Chunk creation
  - [ ] Word timestamp handling

- [ ] **4.2.3** Frame extraction pipeline
  - [ ] `src/application/pipelines/frame_extraction.py`
  - [ ] Frame extraction
  - [ ] Thumbnail generation
  - [ ] Chunk creation

- [ ] **4.2.4** Video chunking pipeline
  - [ ] `src/application/pipelines/video_chunking.py`
  - [ ] Video segmentation
  - [ ] Size optimization
  - [ ] Chunk creation

- [ ] **4.2.5** Embedding pipeline
  - [ ] `src/application/pipelines/embedding.py`
  - [ ] Text embedding (transcripts)
  - [ ] Image embedding (frames)
  - [ ] Video description embedding
  - [ ] Vector storage

#### 4.3 Services

- [x] **4.3.1** Ingestion service
  - [x] `src/application/services/ingestion.py`
  - [x] Pipeline orchestration
  - [x] Status management
  - [x] Error handling

- [x] **4.3.2** Chunking service
  - [x] `src/application/services/chunking.py`
  - [x] Transcript chunking
  - [x] Frame/Audio/Video chunking

- [x] **4.3.3** Storage service
  - [x] `src/application/services/storage.py`
  - [x] Blob storage operations
  - [x] Presigned URL generation

- [x] **4.3.4** Embedding service
  - [x] `src/application/services/embedding.py`
  - [x] Text/Image embedding
  - [x] Vector storage

- [ ] **4.3.5** Query service
  - [ ] `src/application/services/query.py`
  - [ ] Vector search
  - [ ] Context retrieval
  - [ ] LLM generation
  - [ ] Citation building

- [ ] **4.3.6** Source retrieval service
  - [ ] `src/application/services/source_retrieval.py`
  - [ ] Presigned URL generation
  - [ ] Artifact assembly

- [ ] **4.3.7** Video management service
  - [ ] `src/application/services/video_management.py`
  - [ ] List videos
  - [ ] Delete video

#### 4.4 Application Tests

- [ ] **4.4.1** Unit tests for pipelines (mocked infra)
- [ ] **4.4.2** Unit tests for services (mocked infra)
- [ ] **4.4.3** Integration tests for full flows

---

## Phase 5: API Layer ✅

**Goal**: Expose functionality via MCP and REST.

**Status**: COMPLETED (tests pending)

### Tasks

#### 5.1 FastAPI Setup

- [x] **5.1.1** Create app factory
  - [x] `src/api/main.py`
  - [x] Lifespan management
  - [x] Middleware setup

- [x] **5.1.2** Create dependency injection
  - [x] `src/api/dependencies.py`
  - [x] Settings injection
  - [x] Service injection

- [x] **5.1.3** Create middleware
  - [x] `src/api/middleware/logging.py`
  - [x] `src/api/middleware/error_handler.py`
  - [x] Request ID tracking
  - [x] Error formatting

#### 5.2 REST Endpoints

- [x] **5.2.1** Ingestion routes
  - [x] `src/api/openapi/routes/ingestion.py`
  - [x] `POST /videos/ingest`
  - [x] `GET /videos/{id}/status`

- [x] **5.2.2** Query routes
  - [x] `src/api/openapi/routes/query.py`
  - [x] `POST /videos/{id}/query`

- [x] **5.2.3** Source routes
  - [x] `src/api/openapi/routes/sources.py`
  - [x] `GET /videos/{id}/sources`

- [x] **5.2.4** Management routes
  - [x] `src/api/openapi/routes/videos.py`
  - [x] `GET /videos`
  - [x] `GET /videos/{id}`
  - [x] `DELETE /videos/{id}`

- [x] **5.2.5** Health routes
  - [x] `src/api/openapi/routes/health.py`
  - [x] `GET /health`
  - [x] `GET /health/live`
  - [x] `GET /health/ready`

#### 5.3 MCP Server

- [x] **5.3.1** MCP protocol implementation
  - [x] `src/api/mcp/server.py`
  - [x] Tool registration
  - [x] Request handling

- [x] **5.3.2** Tool definitions
  - [x] `ingest_video` tool
  - [x] `get_ingestion_status` tool
  - [x] `query_video` tool
  - [x] `get_sources` tool
  - [x] `list_videos` tool
  - [x] `delete_video` tool

#### 5.4 API Tests

- [ ] **5.4.1** Unit tests for routes
- [ ] **5.4.2** Integration tests for endpoints
- [ ] **5.4.3** E2E tests for MCP protocol

---

## Phase 6: Integration & Polish ⏳

**Goal**: Full system integration, testing, and documentation.

**Status**: NOT STARTED

### Tasks

#### 6.1 Full Integration Tests

- [ ] **6.1.1** End-to-end ingestion flow
  - [ ] Download → Transcribe → Extract → Embed → Store

- [ ] **6.1.2** End-to-end query flow
  - [ ] Query → Search → Retrieve → Generate → Cite

- [ ] **6.1.3** MCP protocol compliance tests

#### 6.2 Performance Optimization

- [ ] **6.2.1** Add caching where appropriate
- [ ] **6.2.2** Optimize batch operations
- [ ] **6.2.3** Profile and optimize hot paths

#### 6.3 Documentation

- [ ] **6.3.1** Generate OpenAPI spec
- [ ] **6.3.2** Write API usage examples
- [ ] **6.3.3** Create README with quick start

#### 6.4 Deployment

- [ ] **6.4.1** Finalize Dockerfile
- [ ] **6.4.2** Create Kubernetes manifests
- [ ] **6.4.3** Set up CI/CD pipeline
- [ ] **6.4.4** Configure ArgoCD

---

## Phase 7: Future Enhancements ⏳

**Goal**: Features for future iterations (not in initial release).

**Status**: BACKLOG

### Potential Tasks

- [ ] **7.1** Webhook notifications for ingestion completion
- [ ] **7.2** Batch ingestion (multiple videos)
- [ ] **7.3** Playlist support
- [ ] **7.4** Live video support (streaming)
- [ ] **7.5** Multi-language transcription
- [ ] **7.6** Speaker diarization
- [ ] **7.7** Custom embedding models
- [ ] **7.8** Fine-tuned LLM for video Q&A
- [ ] **7.9** Video summarization tool
- [ ] **7.10** Timeline visualization
- [ ] **7.11** Collaborative features (sharing, annotations)
- [ ] **7.12** Rate limiting with Redis
- [ ] **7.13** Authentication & authorization
- [ ] **7.14** Multi-tenancy support

---

## Task Dependencies

```
Phase 0 (Setup) ✅
    │
    ▼
Phase 1 (Commons) ✅
    │
    ├─────────────────┐
    ▼                 ▼
Phase 2 (Domain) ✅  Phase 3 (Infrastructure) ✅
    │                 │
    └────────┬────────┘
             ▼
      Phase 4 (Application) 🔄
             │
             ▼
      Phase 5 (API) ✅
             │
             ▼
      Phase 6 (Integration) ⏳ ← NEXT FOCUS
             │
             ▼
      Phase 7 (Future) ⏳
```

---

## Progress Summary

| Phase | Status | Completed | Remaining |
|-------|--------|-----------|-----------|
| **Phase 0** | ✅ Complete | 7/7 | 0 |
| **Phase 1** | ✅ Complete | 9/9 | 0 |
| **Phase 2** | ✅ Complete | 10/10 | 0 |
| **Phase 3** | ✅ Complete* | 10/14 | 4 (tests) |
| **Phase 4** | 🔄 In Progress | 6/14 | 8 |
| **Phase 5** | ✅ Complete* | 10/13 | 3 (tests) |
| **Phase 6** | ⏳ Not Started | 0/8 | 8 |
| **Total** | - | 52/75 | 23 |

*Phase 3 and 5 implementation complete, tests pending

---

## Definition of Done

A task is considered complete when:

1. **Code Complete**: Implementation matches specification
2. **Tests Pass**: Unit tests with >80% coverage
3. **Type Checked**: No mypy errors
4. **Linted**: No ruff errors
5. **Documented**: Docstrings for public APIs
6. **Reviewed**: Code review approved (if applicable)
