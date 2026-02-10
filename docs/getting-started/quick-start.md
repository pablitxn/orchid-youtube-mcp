# Quick Start

Get YouTube RAG Server running in 5 minutes.

## 1. Clone and Install

```bash
# Clone the repository
git clone https://github.com/youtube-rag-server/youtube-rag-server.git
cd youtube-rag-server

# Install with uv
uv sync --dev
```

## 2. Start Infrastructure

```bash
# Start MinIO, Qdrant, and MongoDB
docker-compose up -d

# Verify services are running
docker-compose ps
```

Services will be available at:

| Service | URL | Credentials |
|---------|-----|-------------|
| MinIO Console | http://localhost:9001 | `minioadmin` / `minioadmin` |
| Qdrant Dashboard | http://localhost:6333/dashboard | - |
| MongoDB | localhost:27017 | - |

## 3. Configure Environment

```bash
# Copy the example environment file
cp .env.example .env

# Edit with your API keys
```

Required environment variables:

```env
# OpenAI for transcription and embeddings
YOUTUBE_RAG__TRANSCRIPTION__API_KEY=sk-...
YOUTUBE_RAG__EMBEDDINGS__TEXT__API_KEY=sk-...
YOUTUBE_RAG__LLM__API_KEY=sk-...
```

## 4. Start the Server

```bash
# Run the development server
uvicorn src.adapters.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at http://localhost:8000

- OpenAPI docs: http://localhost:8000/docs
- Health check: http://localhost:8000/health

## Quality Baseline

Use the shared commons-first baseline for daily checks:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -m "not integration and not e2e"
```

## 5. Ingest Your First Video

=== "cURL"

    ```bash
    curl -X POST http://localhost:8000/api/v1/videos/ingest \
      -H "Content-Type: application/json" \
      -d '{
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "extract_frames": true,
        "frame_interval_seconds": 5
      }'
    ```

=== "Python"

    ```python
    import httpx

    async with httpx.AsyncClient() as client:
        response = await client.post(
            "http://localhost:8000/api/v1/videos/ingest",
            json={
                "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                "extract_frames": True,
                "frame_interval_seconds": 5
            }
        )
        result = response.json()
        print(f"Video ID: {result['video_id']}")
    ```

Response:

```json
{
  "video_id": "550e8400-e29b-41d4-a716-446655440000",
  "youtube_id": "dQw4w9WgXcQ",
  "title": "Rick Astley - Never Gonna Give You Up",
  "status": "processing",
  "progress": {
    "current_step": "downloading",
    "overall_progress": 0.1
  }
}
```

## 6. Check Ingestion Status

```bash
curl http://localhost:8000/api/v1/videos/550e8400.../status
```

Wait until status is `ready`:

```json
{
  "video_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "ready",
  "chunk_counts": {
    "transcript": 42,
    "frame": 85,
    "audio": 0,
    "video": 0
  }
}
```

## 7. Query the Video

=== "cURL"

    ```bash
    curl -X POST http://localhost:8000/api/v1/videos/550e8400.../query \
      -H "Content-Type: application/json" \
      -d '{
        "query": "What is this video about?"
      }'
    ```

=== "Python"

    ```python
    response = await client.post(
        f"http://localhost:8000/api/v1/videos/{video_id}/query",
        json={"query": "What is this video about?"}
    )
    result = response.json()

    print(f"Answer: {result['answer']}")
    for citation in result['citations']:
        print(f"  [{citation['timestamp']}] {citation['preview']}")
    ```

Response with citations:

```json
{
  "answer": "This is a music video for 'Never Gonna Give You Up' by Rick Astley...",
  "citations": [
    {
      "id": "cit_001",
      "timestamp_range": {"start": 0, "end": 30},
      "timestamp_display": "0:00 - 0:30",
      "modality": "transcript",
      "preview": "We're no strangers to love...",
      "relevance_score": 0.95,
      "youtube_url": "https://youtube.com/watch?v=dQw4w9WgXcQ&t=0"
    }
  ]
}
```

## Next Steps

- :material-book: [Installation Guide](installation.md) - Detailed setup options
- :material-architecture: [Architecture Overview](../architecture/index.md) - Understand the system
- :material-api: [API Reference](../api/index.md) - Full API documentation
- :material-cog: [Configuration](../configuration/index.md) - Customize settings

## Troubleshooting

### FFmpeg not found

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows (with Chocolatey)
choco install ffmpeg
```

### Docker services won't start

```bash
# Check for port conflicts
docker-compose down
docker-compose up -d

# View logs
docker-compose logs -f
```

### OpenAI API errors

Ensure your API key is valid and has access to:

- `whisper-1` model (transcription)
- `text-embedding-3-small` model (embeddings)
- `gpt-4o` model (LLM queries)
