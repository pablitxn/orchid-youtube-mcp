# Implementation Tasks

## Overview

This document breaks down the implementation into phases with specific tasks. Each phase builds upon the previous one, enabling incremental development and testing.

---

## Phase 0: Project Setup

**Goal**: Initialize the project with all tooling and base structure.

### Tasks

- [ ] **0.1** Initialize Poetry project with Python 3.11+
  ```bash
  poetry init
  poetry add python@^3.11
  ```

- [ ] **0.2** Configure development tools
  - [ ] Add `ruff` for linting
  - [ ] Add `mypy` for type checking
  - [ ] Add `pytest`, `pytest-cov`, `pytest-asyncio` for testing
  - [ ] Create `pyproject.toml` with tool configurations

- [ ] **0.3** Create directory structure
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

- [ ] **0.4** Set up pre-commit hooks
  - [ ] Ruff linting
  - [ ] Mypy type checking
  - [ ] Conventional commits

- [ ] **0.5** Create base configuration files
  - [ ] `config/appsettings.json`
  - [ ] `config/appsettings.dev.json`
  - [ ] `.env.example`

- [ ] **0.6** Set up Docker environment
  - [ ] Create `Dockerfile`
  - [ ] Create `docker-compose.yml` with MinIO, Qdrant, MongoDB

- [ ] **0.7** Initialize Git repository
  - [ ] Create `.gitignore`
  - [ ] Initial commit

---

## Phase 1: Commons Package

**Goal**: Build the shared utilities that all other layers depend on.

### Tasks

#### 1.1 Settings System

- [ ] **1.1.1** Create Pydantic settings models
  - [ ] `src/commons/settings/models.py`
  - [ ] All settings classes from 05-CONFIGURATION.md

- [ ] **1.1.2** Implement settings loader
  - [ ] `src/commons/settings/loader.py`
  - [ ] JSON file loading
  - [ ] Environment variable merging
  - [ ] Environment-specific overrides

- [ ] **1.1.3** Write unit tests for settings
  - [ ] Test default values
  - [ ] Test environment override
  - [ ] Test validation

#### 1.2 Telemetry

- [ ] **1.2.1** Create structured logger
  - [ ] `src/commons/telemetry/logger.py`
  - [ ] JSON formatted output
  - [ ] Correlation ID support
  - [ ] Context management

- [ ] **1.2.2** Create decorators
  - [ ] `src/commons/telemetry/decorators.py`
  - [ ] `@trace` for function tracing
  - [ ] `@log_exceptions` for error logging
  - [ ] `@timed` for performance metrics

- [ ] **1.2.3** Write unit tests for telemetry

#### 1.3 Infrastructure Base Classes

- [ ] **1.3.1** Create blob storage ABC
  - [ ] `src/commons/infrastructure/blob/base.py`
  - [ ] All methods from 04-INFRASTRUCTURE.md

- [ ] **1.3.2** Create vector DB ABC
  - [ ] `src/commons/infrastructure/vectordb/base.py`

- [ ] **1.3.3** Create document DB ABC
  - [ ] `src/commons/infrastructure/documentdb/base.py`

---

## Phase 2: Domain Layer

**Goal**: Implement all domain models and business logic.

### Tasks

#### 2.1 Core Models

- [ ] **2.1.1** Implement VideoMetadata
  - [ ] `src/domain/models/video.py`
  - [ ] `VideoStatus` enum
  - [ ] `VideoMetadata` model
  - [ ] Validation logic

- [ ] **2.1.2** Implement Chunk models
  - [ ] `src/domain/models/chunk.py`
  - [ ] `Modality` enum
  - [ ] `BaseChunk` abstract class
  - [ ] `TranscriptChunk` with word timestamps
  - [ ] `FrameChunk` with image metadata
  - [ ] `AudioChunk` with audio metadata
  - [ ] `VideoChunk` with video segment metadata

- [ ] **2.1.3** Implement Embedding models
  - [ ] `src/domain/models/embedding.py`
  - [ ] `EmbeddingVector` model

- [ ] **2.1.4** Implement Citation models
  - [ ] `src/domain/models/citation.py`
  - [ ] `TimestampRange` value object
  - [ ] `SourceCitation` model

#### 2.2 Value Objects

- [ ] **2.2.1** Implement YouTubeVideoId
  - [ ] URL parsing
  - [ ] Validation
  - [ ] URL generation

- [ ] **2.2.2** Implement ChunkingConfig
  - [ ] All chunking parameters

#### 2.3 Domain Exceptions

- [ ] **2.3.1** Create exception hierarchy
  - [ ] `src/domain/exceptions.py`
  - [ ] All exceptions from 02-DOMAIN-MODELS.md

#### 2.4 Domain Tests

- [ ] **2.4.1** Unit tests for all models
- [ ] **2.4.2** Unit tests for value objects
- [ ] **2.4.3** Unit tests for URL parsing

---

## Phase 3: Infrastructure Layer

**Goal**: Implement concrete infrastructure providers.

### Tasks

#### 3.1 Blob Storage

- [ ] **3.1.1** Implement MinIO provider
  - [ ] `src/commons/infrastructure/blob/minio.py`
  - [ ] All CRUD operations
  - [ ] Presigned URL generation

- [ ] **3.1.2** Integration tests with testcontainers
  - [ ] Upload/download tests
  - [ ] Presigned URL tests

#### 3.2 Vector Database

- [ ] **3.2.1** Implement Qdrant provider
  - [ ] `src/commons/infrastructure/vectordb/qdrant.py`
  - [ ] Collection management
  - [ ] Vector upsert/search
  - [ ] Filtering

- [ ] **3.2.2** Integration tests with testcontainers

#### 3.3 Document Database

- [ ] **3.3.1** Implement MongoDB provider
  - [ ] `src/commons/infrastructure/documentdb/mongodb.py`
  - [ ] CRUD operations
  - [ ] Query building

- [ ] **3.3.2** Integration tests with testcontainers

#### 3.4 YouTube Downloader

- [ ] **3.4.1** Implement yt-dlp wrapper
  - [ ] `src/infrastructure/youtube/downloader.py`
  - [ ] Video download
  - [ ] Audio extraction
  - [ ] Metadata fetching

- [ ] **3.4.2** Unit tests with mocked responses

#### 3.5 AI Services (Abstract + One Provider Each)

- [ ] **3.5.1** Transcription service
  - [ ] `src/infrastructure/transcription/base.py`
  - [ ] `src/infrastructure/transcription/openai_whisper.py`

- [ ] **3.5.2** Embedding service
  - [ ] `src/infrastructure/embeddings/base.py`
  - [ ] `src/infrastructure/embeddings/openai.py` (text)
  - [ ] `src/infrastructure/embeddings/clip.py` (image)

- [ ] **3.5.3** LLM service
  - [ ] `src/infrastructure/llm/base.py`
  - [ ] `src/infrastructure/llm/openai.py`

#### 3.6 Video Processing

- [ ] **3.6.1** Frame extractor
  - [ ] `src/infrastructure/video/frame_extractor.py`
  - [ ] FFmpeg integration
  - [ ] Thumbnail generation

- [ ] **3.6.2** Video chunker
  - [ ] `src/infrastructure/video/chunker.py`
  - [ ] Segment splitting
  - [ ] Size management

#### 3.7 Infrastructure Factory

- [ ] **3.7.1** Implement factory pattern
  - [ ] `src/infrastructure/factory.py`
  - [ ] Provider registration
  - [ ] Configuration-based instantiation

---

## Phase 4: Application Layer

**Goal**: Implement business logic orchestration.

### Tasks

#### 4.1 DTOs

- [ ] **4.1.1** Create request DTOs
  - [ ] `src/application/dtos/requests.py`
  - [ ] `IngestVideoRequest`
  - [ ] `QueryVideoRequest`
  - [ ] `GetSourcesRequest`

- [ ] **4.1.2** Create response DTOs
  - [ ] `src/application/dtos/responses.py`
  - [ ] `IngestVideoResponse`
  - [ ] `QueryVideoResponse`
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

- [ ] **4.3.1** Ingestion service
  - [ ] `src/application/services/ingestion.py`
  - [ ] Pipeline orchestration
  - [ ] Status management
  - [ ] Error handling

- [ ] **4.3.2** Query service
  - [ ] `src/application/services/query.py`
  - [ ] Vector search
  - [ ] Context retrieval
  - [ ] LLM generation
  - [ ] Citation building

- [ ] **4.3.3** Source retrieval service
  - [ ] `src/application/services/source_retrieval.py`
  - [ ] Presigned URL generation
  - [ ] Artifact assembly

#### 4.4 Application Tests

- [ ] **4.4.1** Unit tests for pipelines (mocked infra)
- [ ] **4.4.2** Unit tests for services (mocked infra)
- [ ] **4.4.3** Integration tests for full flows

---

## Phase 5: API Layer

**Goal**: Expose functionality via MCP and REST.

### Tasks

#### 5.1 FastAPI Setup

- [ ] **5.1.1** Create app factory
  - [ ] `src/api/main.py`
  - [ ] Lifespan management
  - [ ] Middleware setup

- [ ] **5.1.2** Create dependency injection
  - [ ] `src/api/dependencies.py`
  - [ ] Settings injection
  - [ ] Service injection

- [ ] **5.1.3** Create middleware
  - [ ] `src/api/middleware/logging.py`
  - [ ] `src/api/middleware/error_handler.py`
  - [ ] Request ID tracking
  - [ ] Error formatting

#### 5.2 REST Endpoints

- [ ] **5.2.1** Ingestion routes
  - [ ] `src/api/openapi/routes/ingestion.py`
  - [ ] `POST /videos/ingest`
  - [ ] `GET /videos/{id}/status`

- [ ] **5.2.2** Query routes
  - [ ] `src/api/openapi/routes/query.py`
  - [ ] `POST /videos/{id}/query`

- [ ] **5.2.3** Source routes
  - [ ] `src/api/openapi/routes/sources.py`
  - [ ] `GET /videos/{id}/sources`

- [ ] **5.2.4** Management routes
  - [ ] `src/api/openapi/routes/videos.py`
  - [ ] `GET /videos`
  - [ ] `DELETE /videos/{id}`

- [ ] **5.2.5** Health routes
  - [ ] `src/api/openapi/routes/health.py`
  - [ ] `GET /health`
  - [ ] `GET /health/live`
  - [ ] `GET /health/ready`

#### 5.3 MCP Server

- [ ] **5.3.1** MCP protocol implementation
  - [ ] `src/api/mcp/server.py`
  - [ ] Tool registration
  - [ ] Request handling

- [ ] **5.3.2** Tool definitions
  - [ ] `ingest_video` tool
  - [ ] `get_ingestion_status` tool
  - [ ] `query_video` tool
  - [ ] `get_sources` tool
  - [ ] `list_videos` tool
  - [ ] `delete_video` tool

#### 5.4 API Tests

- [ ] **5.4.1** Unit tests for routes
- [ ] **5.4.2** Integration tests for endpoints
- [ ] **5.4.3** E2E tests for MCP protocol

---

## Phase 6: Integration & Polish

**Goal**: Full system integration, testing, and documentation.

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

## Phase 7: Future Enhancements

**Goal**: Features for future iterations (not in initial release).

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
Phase 0 (Setup)
    │
    ▼
Phase 1 (Commons)
    │
    ├─────────────────┐
    ▼                 ▼
Phase 2 (Domain)   Phase 3 (Infrastructure)
    │                 │
    └────────┬────────┘
             ▼
      Phase 4 (Application)
             │
             ▼
      Phase 5 (API)
             │
             ▼
      Phase 6 (Integration)
             │
             ▼
      Phase 7 (Future)
```

---

## Estimated Effort

| Phase | Tasks | Complexity | Notes |
|-------|-------|------------|-------|
| **Phase 0** | 7 | Low | Setup, mostly boilerplate |
| **Phase 1** | 9 | Medium | Core utilities |
| **Phase 2** | 10 | Low | Pure models, no I/O |
| **Phase 3** | 14 | High | External integrations |
| **Phase 4** | 14 | High | Business logic |
| **Phase 5** | 13 | Medium | API layer |
| **Phase 6** | 8 | Medium | Polish |
| **Total** | 75 | - | Initial release |

---

## Definition of Done

A task is considered complete when:

1. **Code Complete**: Implementation matches specification
2. **Tests Pass**: Unit tests with >80% coverage
3. **Type Checked**: No mypy errors
4. **Linted**: No ruff errors
5. **Documented**: Docstrings for public APIs
6. **Reviewed**: Code review approved (if applicable)
