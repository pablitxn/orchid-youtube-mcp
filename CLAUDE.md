# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

YouTube RAG Server - An MCP Server + OpenAPI Plugin that enables LLM agents to index and query YouTube video content in a multimodal fashion (text, audio, frames, video segments), with temporal precision for source citations.

## Common Commands

### Development Setup
```bash
# Install dependencies (uses uv)
uv sync --dev

# Start infrastructure services (MinIO, Qdrant, MongoDB)
docker-compose up -d

# Run the server (when implemented)
uvicorn src.api.main:app --reload
```

### Code Quality
```bash
# Run all checks (linting, formatting, type checking)
ruff check src tests
ruff format src tests
mypy src

# Run pre-commit hooks manually
pre-commit run --all-files
```

### Testing
```bash
# Run all tests with coverage
pytest

# Run specific test file
pytest tests/unit/test_example.py

# Run tests by marker
pytest -m unit
pytest -m integration
pytest -m e2e

# Run single test function
pytest tests/unit/test_example.py::test_function_name -v
```

## Architecture

The project follows a **layered hexagonal architecture** with clear separation of concerns:

```
src/
├── commons/          # Shared utilities (settings, telemetry, infrastructure ABCs)
├── domain/           # Pure business entities (VideoMetadata, Chunks, Embeddings, Citations)
├── application/      # Business logic orchestration (services, pipelines, DTOs)
├── infrastructure/   # External service implementations (YouTube, transcription, embeddings, LLM)
└── api/              # Exposure layer (FastAPI + MCP server)
```

### Key Design Principles
- **Dependency Inversion**: All infrastructure components implement abstract base classes in `src/commons/infrastructure/`
- **Multimodal First**: Content is chunked into TranscriptChunk, FrameChunk, AudioChunk, and VideoChunk with unified temporal positioning
- **Temporal Citation**: Every query response includes precise timestamps linking back to source material

### Configuration
- Base config: `config/appsettings.json`
- Environment overrides: `config/appsettings.{env}.json`
- Environment variables use prefix `YOUTUBE_RAG__` with double underscore for nesting (e.g., `YOUTUBE_RAG__APP__ENVIRONMENT=prod`)

### Infrastructure Services
- **MinIO** (port 9000/9001): S3-compatible blob storage for videos, audio, frames
- **Qdrant** (port 6333/6334): Vector database for semantic search embeddings
- **MongoDB** (port 27017): Document database for metadata and chunks

## Code Style

- Python 3.11+ required
- Ruff for linting and formatting (line length 88)
- Mypy with strict mode enabled
- Conventional commits enforced: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `build`, `ci`, `chore`, `revert`

## MCP Tools

The server exposes these tools for AI agent integration:
- `ingest_video`: Download and index a YouTube video
- `get_ingestion_status`: Check processing status
- `query_video`: Semantic search with temporal citations
- `get_sources`: Retrieve source artifacts (frames, audio clips, video segments)
- `list_videos`: List indexed videos with filtering
- `delete_video`: Remove video and all associated data
