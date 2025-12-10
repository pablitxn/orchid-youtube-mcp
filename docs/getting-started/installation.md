# Installation

Detailed installation instructions for YouTube RAG Server.

## System Requirements

| Requirement | Minimum | Recommended |
|-------------|---------|-------------|
| **Python** | 3.11 | 3.12 |
| **RAM** | 4 GB | 8 GB+ |
| **Disk** | 10 GB | 50 GB+ |
| **Docker** | 20.10+ | Latest |
| **FFmpeg** | 4.4+ | 6.0+ |

## Installation Methods

### Using uv (Recommended)

[uv](https://docs.astral.sh/uv/) is a fast Python package manager written in Rust.

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone repository
git clone https://github.com/youtube-rag-server/youtube-rag-server.git
cd youtube-rag-server

# Create virtual environment and install dependencies
uv sync

# Install with development dependencies
uv sync --dev

# Install with documentation dependencies
uv sync --extra docs
```

### Using pip

```bash
# Clone repository
git clone https://github.com/youtube-rag-server/youtube-rag-server.git
cd youtube-rag-server

# Create virtual environment
python -m venv .venv

# Activate (Linux/macOS)
source .venv/bin/activate

# Activate (Windows)
.venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"
```

### Using Poetry

```bash
# Clone repository
git clone https://github.com/youtube-rag-server/youtube-rag-server.git
cd youtube-rag-server

# Install with Poetry
poetry install --with dev
```

## FFmpeg Installation

FFmpeg is required for video and audio processing.

=== "macOS"

    ```bash
    # Using Homebrew
    brew install ffmpeg

    # Verify installation
    ffmpeg -version
    ```

=== "Ubuntu/Debian"

    ```bash
    sudo apt update
    sudo apt install ffmpeg

    # Verify installation
    ffmpeg -version
    ```

=== "Windows"

    ```powershell
    # Using Chocolatey
    choco install ffmpeg

    # Using Scoop
    scoop install ffmpeg

    # Or download from https://ffmpeg.org/download.html
    # Add to PATH

    # Verify installation
    ffmpeg -version
    ```

=== "Docker"

    FFmpeg is included in the Docker image, no separate installation needed.

## Infrastructure Setup

### Local Development (Docker Compose)

```bash
# Start all services
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Stop and remove volumes
docker-compose down -v
```

#### Services Overview

```yaml
# docker-compose.yml services
services:
  minio:      # S3-compatible object storage
  qdrant:     # Vector database
  mongodb:    # Document database
```

| Service | Port(s) | Purpose |
|---------|---------|---------|
| MinIO | 9000, 9001 | Blob storage (videos, frames, audio) |
| Qdrant | 6333, 6334 | Vector embeddings storage |
| MongoDB | 27017 | Metadata and chunk storage |

### Cloud Infrastructure

For production deployments, configure cloud providers:

```env
# AWS S3
YOUTUBE_RAG__BLOB_STORAGE__PROVIDER=s3
YOUTUBE_RAG__BLOB_STORAGE__ENDPOINT=https://s3.amazonaws.com
YOUTUBE_RAG__BLOB_STORAGE__ACCESS_KEY=AKIA...
YOUTUBE_RAG__BLOB_STORAGE__SECRET_KEY=...

# Qdrant Cloud
YOUTUBE_RAG__VECTOR_DB__PROVIDER=qdrant
YOUTUBE_RAG__VECTOR_DB__HOST=xyz-123.aws.cloud.qdrant.io
YOUTUBE_RAG__VECTOR_DB__API_KEY=...

# MongoDB Atlas
YOUTUBE_RAG__DOCUMENT_DB__PROVIDER=mongodb
YOUTUBE_RAG__DOCUMENT_DB__HOST=cluster0.abc123.mongodb.net
YOUTUBE_RAG__DOCUMENT_DB__USERNAME=...
YOUTUBE_RAG__DOCUMENT_DB__PASSWORD=...
```

## API Keys Configuration

### Required API Keys

Create a `.env` file in the project root:

```env
# OpenAI (required for default providers)
YOUTUBE_RAG__TRANSCRIPTION__API_KEY=sk-...
YOUTUBE_RAG__EMBEDDINGS__TEXT__API_KEY=sk-...
YOUTUBE_RAG__LLM__API_KEY=sk-...
```

### Alternative Providers

=== "Anthropic (LLM)"

    ```env
    YOUTUBE_RAG__LLM__PROVIDER=anthropic
    YOUTUBE_RAG__LLM__API_KEY=sk-ant-...
    YOUTUBE_RAG__LLM__MODEL=claude-3-5-sonnet-20241022
    ```

=== "Deepgram (Transcription)"

    ```env
    YOUTUBE_RAG__TRANSCRIPTION__PROVIDER=deepgram
    YOUTUBE_RAG__TRANSCRIPTION__API_KEY=...
    ```

=== "Azure OpenAI"

    ```env
    YOUTUBE_RAG__LLM__PROVIDER=azure_openai
    YOUTUBE_RAG__LLM__API_KEY=...
    YOUTUBE_RAG__LLM__ENDPOINT=https://your-resource.openai.azure.com/
    YOUTUBE_RAG__LLM__DEPLOYMENT_NAME=gpt-4o
    ```

## Verify Installation

### Check Python Environment

```bash
# Verify Python version
python --version  # Should be 3.11+

# Verify package installation
python -c "from src.domain import VideoMetadata; print('Domain OK')"
python -c "from src.application import VideoIngestionService; print('Application OK')"
```

### Check Infrastructure

```bash
# MinIO
curl http://localhost:9000/minio/health/live

# Qdrant
curl http://localhost:6333/healthz

# MongoDB
docker exec mongodb mongosh --eval "db.runCommand('ping')"
```

### Run Tests

```bash
# All tests
pytest

# Unit tests only
pytest -m unit

# With coverage
pytest --cov=src --cov-report=html
```

### Start Development Server

```bash
# Run with auto-reload
uvicorn src.api.main:app --reload --host 0.0.0.0 --port 8000

# Check health
curl http://localhost:8000/health
```

## IDE Setup

### VS Code

Recommended extensions:

```json
// .vscode/extensions.json
{
  "recommendations": [
    "ms-python.python",
    "ms-python.vscode-pylance",
    "charliermarsh.ruff",
    "tamasfe.even-better-toml"
  ]
}
```

Settings:

```json
// .vscode/settings.json
{
  "python.defaultInterpreterPath": ".venv/bin/python",
  "python.analysis.typeCheckingMode": "strict",
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  }
}
```

### PyCharm

1. Open project folder
2. Configure interpreter: `.venv/bin/python`
3. Enable Ruff plugin for linting
4. Enable Mypy plugin for type checking

## Troubleshooting

### Common Issues

??? question "Import errors after installation"

    Ensure you're using the correct virtual environment:

    ```bash
    which python  # Should point to .venv
    pip list | grep youtube-rag
    ```

??? question "Docker permission denied"

    Add your user to the docker group:

    ```bash
    sudo usermod -aG docker $USER
    # Log out and back in
    ```

??? question "FFmpeg codec errors"

    Ensure FFmpeg was compiled with required codecs:

    ```bash
    ffmpeg -encoders | grep libx264
    ffmpeg -decoders | grep h264
    ```

??? question "MongoDB connection refused"

    Check if MongoDB is running:

    ```bash
    docker-compose logs mongodb
    docker-compose restart mongodb
    ```

## Next Steps

- [Quick Start](quick-start.md) - Run your first video ingestion
- [Configuration](../configuration/index.md) - Customize settings
- [Development Setup](../development/local-setup.md) - Full development environment
