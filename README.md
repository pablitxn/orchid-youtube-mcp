# YouTube MCP (YouTube RAG Server)

Server for indexing and querying YouTube content with multimodal RAG (transcription + frames + metadata) via:
- REST API (FastAPI)
- MCP server for agents

The goal is to answer questions about videos with temporal citations and access to source artifacts.

## What this project does

- YouTube video ingestion (yt-dlp + FFmpeg)
- Transcription (Whisper/OpenAI)
- Transcript/frame/audio/video chunking
- Embeddings and semantic search (Qdrant)
- Metadata and processing state (MongoDB)
- Binary artifacts and signed URLs (MinIO/S3-compatible)
- Responses with citations (`timestamp_range`, `content_preview`, `youtube_url`)

## Architecture (overview)

Main structure:

```text
src/
  api/             # REST + MCP
  application/     # business services (ingestion/query)
  domain/          # models and value objects
  infrastructure/  # concrete providers (yt-dlp, OpenAI, FFmpeg, etc.)
  commons/         # runtime integration, settings, observability and adapters
tests/
config/
docs/
```

General flow:
1. `POST /v1/videos/ingest` starts the ingestion pipeline.
2. Chunks and embeddings are persisted.
3. `POST /v1/videos/{video_id}/query` performs semantic search and synthesizes a response.
4. `GET /v1/videos/{video_id}/sources` returns artifacts associated with citations.

## Local quickstart

### Requirements

- Python 3.11+
- `uv`
- Docker + Docker Compose
- FFmpeg

### 1) Install dependencies

```bash
uv sync --dev
```

### 2) Configure environment

```bash
cp .env.example .env
```

Critical variables:
- `YOUTUBE_RAG__TRANSCRIPTION__API_KEY`
- `YOUTUBE_RAG__EMBEDDINGS__TEXT__API_KEY`
- `YOUTUBE_RAG__LLM__API_KEY`

### 3) Start local infrastructure

```bash
docker-compose up -d
docker-compose ps
```

Services:
- MinIO: `http://localhost:9001`
- Qdrant: `http://localhost:6333/dashboard`
- MongoDB: `localhost:27017`

### 4) Run the REST API

```bash
uv run uvicorn src.adapters.main:app --reload --host 0.0.0.0 --port 8000
```

- OpenAPI: `http://localhost:8000/docs`
- Health: `http://localhost:8000/health`

## API examples

Ingestion:

```bash
curl -X POST http://localhost:8000/v1/videos/ingest \
  -H "Content-Type: application/json" \
  -d '{
    "youtube_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "extract_frames": true
  }'
```

Query:

```bash
curl -X POST http://localhost:8000/v1/videos/<video_id>/query \
  -H "Content-Type: application/json" \
  -d '{"query":"What is the main topic of the video?"}'
```

Sources by citation:

```bash
curl "http://localhost:8000/v1/videos/<video_id>/sources?citation_ids=cit_001"
```

## MCP server

Available MCP tools:
- `ingest_video`
- `get_ingestion_status`
- `query_video`
- `get_sources`
- `list_videos`
- `delete_video`

Run (stdio):

```bash
uv run python -c "import asyncio; from src.adapters.mcp import run_mcp_server; asyncio.run(run_mcp_server())"
```

## Commons package (`orchid-skills-commons` / `orchid_commons`)

This repo uses `orchid-skills-commons[blob,db,observability]` as a shared runtime base.

Where it integrates:
- `src/infrastructure/runtime.py`: `ResourceManager`, `load_config`, resource startup/shutdown (`multi_bucket`, `qdrant`, `mongodb`).
- `src/infrastructure/observability.py`: logging bootstrap, OpenTelemetry/Langfuse and uvicorn logger wiring.
- `src/infrastructure/infrastructure/blob/multi_bucket_adapter.py`: adapts `MultiBucketBlobRouter` to the local `BlobStorageBase` contract.
- `src/infrastructure/infrastructure/vectordb/commons_adapter.py`: adapts `VectorStore` to the local `VectorDBBase` contract.
- `src/infrastructure/infrastructure/documentdb/commons_adapter.py`: adapts the commons MongoDB resource to the local `DocumentDBBase` contract.

Why it matters:
- Standardizes configuration and lifecycle across repos.
- Allows switching providers with minimal impact on the application layer.
- Centralizes observability and health checks.

## Quality and testing

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run mypy src
uv run pytest
uv run pre-commit run --all-files
```

Notes:
- `pytest` requires minimum coverage of `80%` (`--cov-fail-under=80`).
- Available markers: `unit`, `integration`, `e2e`, `slow`.
