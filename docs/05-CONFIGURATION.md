# Configuration System

## Overview

The configuration system follows a hierarchical loading pattern that supports:
- Environment-specific settings (dev, staging, prod)
- Secrets management via environment variables
- Runtime overrides
- Validation via Pydantic models

---

## Configuration Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                    Runtime Overrides                         │
│               (highest priority - CLI args)                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                  Environment Variables                       │
│              (secrets, deployment-specific)                  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│              appsettings.{environment}.json                  │
│                  (environment-specific)                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                    appsettings.json                          │
│                 (base defaults - lowest priority)            │
└─────────────────────────────────────────────────────────────┘
```

---

## Configuration Files

### Directory Structure

```
config/
├── appsettings.json              # Base defaults
├── appsettings.dev.json          # Development overrides
├── appsettings.staging.json      # Staging overrides
└── appsettings.prod.json         # Production overrides
```

### Base Configuration (appsettings.json)

```json
{
  "app": {
    "name": "youtube-rag-server",
    "version": "0.1.0",
    "environment": "dev",
    "debug": false,
    "log_level": "INFO"
  },

  "server": {
    "host": "0.0.0.0",
    "port": 8000,
    "workers": 1,
    "reload": false,
    "cors_origins": ["*"],
    "api_prefix": "/v1",
    "docs_enabled": true
  },

  "blob_storage": {
    "provider": "minio",
    "endpoint": "localhost:9000",
    "use_ssl": false,
    "region": "us-east-1",
    "buckets": {
      "videos": "rag-videos",
      "chunks": "rag-chunks",
      "frames": "rag-frames"
    },
    "presigned_url_expiry_seconds": 3600
  },

  "vector_db": {
    "provider": "qdrant",
    "host": "localhost",
    "port": 6333,
    "grpc_port": 6334,
    "use_ssl": false,
    "collections": {
      "transcripts": "transcript_embeddings",
      "frames": "frame_embeddings",
      "videos": "video_embeddings"
    },
    "default_limit": 10,
    "score_threshold": 0.7
  },

  "document_db": {
    "provider": "mongodb",
    "host": "localhost",
    "port": 27017,
    "database": "youtube_rag",
    "auth_source": "admin",
    "collections": {
      "videos": "videos",
      "transcript_chunks": "transcript_chunks",
      "frame_chunks": "frame_chunks",
      "audio_chunks": "audio_chunks",
      "video_chunks": "video_chunks",
      "citations": "citations"
    }
  },

  "transcription": {
    "provider": "openai_whisper",
    "model": "whisper-1",
    "language": null,
    "word_timestamps": true,
    "timeout_seconds": 300
  },

  "embeddings": {
    "text": {
      "provider": "openai",
      "model": "text-embedding-3-small",
      "dimensions": 1536,
      "batch_size": 100
    },
    "image": {
      "provider": "clip",
      "model": "ViT-B/32",
      "dimensions": 512,
      "batch_size": 32
    }
  },

  "llm": {
    "provider": "openai",
    "model": "gpt-4o",
    "temperature": 0.7,
    "max_tokens": 2048,
    "timeout_seconds": 60
  },

  "chunking": {
    "transcript": {
      "chunk_seconds": 30,
      "overlap_seconds": 5
    },
    "frame": {
      "interval_seconds": 2.0
    },
    "audio": {
      "chunk_seconds": 60
    },
    "video": {
      "chunk_seconds": 30,
      "overlap_seconds": 2,
      "max_size_mb": 20.0
    }
  },

  "processing": {
    "max_video_duration_seconds": 7200,
    "max_video_size_mb": 2048,
    "concurrent_downloads": 2,
    "retry_attempts": 3,
    "retry_delay_seconds": 5
  },

  "telemetry": {
    "enabled": true,
    "log_format": "json",
    "log_level": "INFO",
    "loki": {
      "enabled": false,
      "endpoint": "http://localhost:3100",
      "batch_size": 100,
      "flush_interval_seconds": 5
    },
    "metrics": {
      "enabled": false,
      "endpoint": "http://localhost:9090"
    }
  },

  "rate_limiting": {
    "enabled": true,
    "storage": "memory",
    "limits": {
      "ingest": {"requests": 10, "window_seconds": 3600},
      "query": {"requests": 100, "window_seconds": 60},
      "sources": {"requests": 200, "window_seconds": 60},
      "list": {"requests": 60, "window_seconds": 60},
      "delete": {"requests": 30, "window_seconds": 3600}
    }
  }
}
```

### Development Overrides (appsettings.dev.json)

```json
{
  "app": {
    "environment": "dev",
    "debug": true,
    "log_level": "DEBUG"
  },

  "server": {
    "reload": true,
    "workers": 1
  },

  "rate_limiting": {
    "enabled": false
  }
}
```

### Staging Overrides (appsettings.staging.json)

```json
{
  "app": {
    "environment": "staging",
    "debug": false,
    "log_level": "INFO"
  },

  "server": {
    "workers": 2,
    "cors_origins": ["https://staging.example.com"]
  },

  "blob_storage": {
    "provider": "s3",
    "use_ssl": true
  },

  "telemetry": {
    "loki": {
      "enabled": true
    }
  }
}
```

### Production Overrides (appsettings.prod.json)

```json
{
  "app": {
    "environment": "prod",
    "debug": false,
    "log_level": "WARNING"
  },

  "server": {
    "workers": 4,
    "docs_enabled": false,
    "cors_origins": ["https://app.example.com"]
  },

  "blob_storage": {
    "provider": "s3",
    "use_ssl": true
  },

  "rate_limiting": {
    "storage": "redis"
  },

  "telemetry": {
    "loki": {
      "enabled": true
    },
    "metrics": {
      "enabled": true
    }
  }
}
```

---

## Environment Variables

Sensitive values and deployment-specific settings are loaded from environment variables.

### Naming Convention

Environment variables follow the pattern:
```
YOUTUBE_RAG__{SECTION}__{KEY}
```

Double underscores (`__`) separate nested keys.

### Required Variables

```bash
# Blob Storage Credentials
YOUTUBE_RAG__BLOB_STORAGE__ACCESS_KEY=your-access-key
YOUTUBE_RAG__BLOB_STORAGE__SECRET_KEY=your-secret-key

# Document DB Credentials
YOUTUBE_RAG__DOCUMENT_DB__USERNAME=admin
YOUTUBE_RAG__DOCUMENT_DB__PASSWORD=secure-password

# AI Service API Keys
YOUTUBE_RAG__TRANSCRIPTION__API_KEY=sk-...
YOUTUBE_RAG__EMBEDDINGS__TEXT__API_KEY=sk-...
YOUTUBE_RAG__LLM__API_KEY=sk-...

# Optional: YouTube API (for enhanced metadata)
YOUTUBE_RAG__YOUTUBE__API_KEY=AIza...
```

### Azure OpenAI Configuration

```bash
YOUTUBE_RAG__EMBEDDINGS__TEXT__PROVIDER=azure_openai
YOUTUBE_RAG__EMBEDDINGS__TEXT__API_KEY=your-azure-key
YOUTUBE_RAG__EMBEDDINGS__TEXT__ENDPOINT=https://your-resource.openai.azure.com
YOUTUBE_RAG__EMBEDDINGS__TEXT__DEPLOYMENT=text-embedding-3-small

YOUTUBE_RAG__LLM__PROVIDER=azure_openai
YOUTUBE_RAG__LLM__API_KEY=your-azure-key
YOUTUBE_RAG__LLM__ENDPOINT=https://your-resource.openai.azure.com
YOUTUBE_RAG__LLM__DEPLOYMENT=gpt-4o
```

### Google Cloud Configuration

```bash
YOUTUBE_RAG__LLM__PROVIDER=google
YOUTUBE_RAG__LLM__API_KEY=your-google-api-key
# Or use service account
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

---

## Pydantic Settings Models

### Core Settings

```python
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from typing import Literal


class AppSettings(BaseModel):
    name: str = "youtube-rag-server"
    version: str = "0.1.0"
    environment: Literal["dev", "staging", "prod"] = "dev"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1, le=65535)
    workers: int = Field(default=1, ge=1, le=32)
    reload: bool = False
    cors_origins: list[str] = ["*"]
    api_prefix: str = "/v1"
    docs_enabled: bool = True


class BlobStorageSettings(BaseModel):
    provider: Literal["minio", "s3", "gcs", "azure"] = "minio"
    endpoint: str = "localhost:9000"
    access_key: str = ""  # From env
    secret_key: str = ""  # From env
    use_ssl: bool = False
    region: str = "us-east-1"
    buckets: dict[str, str] = {
        "videos": "rag-videos",
        "chunks": "rag-chunks",
        "frames": "rag-frames"
    }
    presigned_url_expiry_seconds: int = 3600


class VectorDBSettings(BaseModel):
    provider: Literal["qdrant", "pinecone", "weaviate"] = "qdrant"
    host: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334
    api_key: str | None = None  # For cloud providers
    use_ssl: bool = False
    collections: dict[str, str] = {
        "transcripts": "transcript_embeddings",
        "frames": "frame_embeddings",
        "videos": "video_embeddings"
    }
    default_limit: int = 10
    score_threshold: float = 0.7


class DocumentDBSettings(BaseModel):
    provider: Literal["mongodb", "postgres"] = "mongodb"
    host: str = "localhost"
    port: int = 27017
    username: str = ""  # From env
    password: str = ""  # From env
    database: str = "youtube_rag"
    auth_source: str = "admin"


class TranscriptionSettings(BaseModel):
    provider: Literal[
        "openai_whisper", "deepgram", "assemblyai",
        "azure_speech", "google_speech"
    ] = "openai_whisper"
    api_key: str = ""  # From env
    model: str = "whisper-1"
    language: str | None = None
    word_timestamps: bool = True
    timeout_seconds: int = 300


class TextEmbeddingSettings(BaseModel):
    provider: Literal["openai", "azure_openai", "cohere", "voyage"] = "openai"
    api_key: str = ""  # From env
    endpoint: str | None = None  # For Azure
    deployment: str | None = None  # For Azure
    model: str = "text-embedding-3-small"
    dimensions: int = 1536
    batch_size: int = 100


class ImageEmbeddingSettings(BaseModel):
    provider: Literal["clip", "vertex"] = "clip"
    model: str = "ViT-B/32"
    dimensions: int = 512
    batch_size: int = 32


class EmbeddingsSettings(BaseModel):
    text: TextEmbeddingSettings = TextEmbeddingSettings()
    image: ImageEmbeddingSettings = ImageEmbeddingSettings()


class LLMSettings(BaseModel):
    provider: Literal["openai", "azure_openai", "anthropic", "google"] = "openai"
    api_key: str = ""  # From env
    endpoint: str | None = None  # For Azure
    deployment: str | None = None  # For Azure
    model: str = "gpt-4o"
    temperature: float = Field(default=0.7, ge=0, le=2)
    max_tokens: int = 2048
    timeout_seconds: int = 60


class ChunkingSettings(BaseModel):
    class TranscriptChunking(BaseModel):
        chunk_seconds: int = 30
        overlap_seconds: int = 5

    class FrameChunking(BaseModel):
        interval_seconds: float = 2.0

    class AudioChunking(BaseModel):
        chunk_seconds: int = 60

    class VideoChunking(BaseModel):
        chunk_seconds: int = 30
        overlap_seconds: int = 2
        max_size_mb: float = 20.0

    transcript: TranscriptChunking = TranscriptChunking()
    frame: FrameChunking = FrameChunking()
    audio: AudioChunking = AudioChunking()
    video: VideoChunking = VideoChunking()


class ProcessingSettings(BaseModel):
    max_video_duration_seconds: int = 7200  # 2 hours
    max_video_size_mb: int = 2048  # 2 GB
    concurrent_downloads: int = 2
    retry_attempts: int = 3
    retry_delay_seconds: int = 5


class TelemetrySettings(BaseModel):
    class LokiSettings(BaseModel):
        enabled: bool = False
        endpoint: str = "http://localhost:3100"
        batch_size: int = 100
        flush_interval_seconds: int = 5

    class MetricsSettings(BaseModel):
        enabled: bool = False
        endpoint: str = "http://localhost:9090"

    enabled: bool = True
    log_format: Literal["json", "text"] = "json"
    log_level: str = "INFO"
    loki: LokiSettings = LokiSettings()
    metrics: MetricsSettings = MetricsSettings()


class RateLimitSettings(BaseModel):
    class LimitConfig(BaseModel):
        requests: int
        window_seconds: int

    enabled: bool = True
    storage: Literal["memory", "redis"] = "memory"
    limits: dict[str, LimitConfig] = {
        "ingest": LimitConfig(requests=10, window_seconds=3600),
        "query": LimitConfig(requests=100, window_seconds=60),
        "sources": LimitConfig(requests=200, window_seconds=60),
        "list": LimitConfig(requests=60, window_seconds=60),
        "delete": LimitConfig(requests=30, window_seconds=3600)
    }
```

### Root Settings Class

```python
class Settings(BaseSettings):
    """Root settings container with environment loading."""

    app: AppSettings = AppSettings()
    server: ServerSettings = ServerSettings()
    blob_storage: BlobStorageSettings = BlobStorageSettings()
    vector_db: VectorDBSettings = VectorDBSettings()
    document_db: DocumentDBSettings = DocumentDBSettings()
    transcription: TranscriptionSettings = TranscriptionSettings()
    embeddings: EmbeddingsSettings = EmbeddingsSettings()
    llm: LLMSettings = LLMSettings()
    chunking: ChunkingSettings = ChunkingSettings()
    processing: ProcessingSettings = ProcessingSettings()
    telemetry: TelemetrySettings = TelemetrySettings()
    rate_limiting: RateLimitSettings = RateLimitSettings()

    model_config = SettingsConfigDict(
        env_prefix="YOUTUBE_RAG__",
        env_nested_delimiter="__",
        case_sensitive=False
    )
```

---

## Settings Loader

```python
import json
from pathlib import Path
from typing import Any


class SettingsLoader:
    """Loads and merges configuration from multiple sources."""

    def __init__(
        self,
        config_dir: Path = Path("config"),
        environment: str | None = None
    ):
        self.config_dir = config_dir
        self.environment = environment or os.getenv(
            "YOUTUBE_RAG__APP__ENVIRONMENT", "dev"
        )

    def load(self) -> Settings:
        """Load settings with proper precedence."""
        # 1. Load base config
        config = self._load_json("appsettings.json")

        # 2. Merge environment-specific config
        env_config = self._load_json(f"appsettings.{self.environment}.json")
        config = self._deep_merge(config, env_config)

        # 3. Create Settings (env vars loaded automatically by Pydantic)
        return Settings(**config)

    def _load_json(self, filename: str) -> dict[str, Any]:
        """Load JSON config file."""
        path = self.config_dir / filename
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return {}

    def _deep_merge(
        self,
        base: dict[str, Any],
        override: dict[str, Any]
    ) -> dict[str, Any]:
        """Deep merge two dictionaries."""
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result


# Global settings instance
_settings: Settings | None = None


def get_settings() -> Settings:
    """Get or create the global settings instance."""
    global _settings
    if _settings is None:
        loader = SettingsLoader()
        _settings = loader.load()
    return _settings
```

---

## Dependency Injection

Use FastAPI's dependency injection with settings:

```python
from fastapi import Depends


def get_blob_storage(
    settings: Settings = Depends(get_settings)
) -> BlobStorageBase:
    """Create blob storage from settings."""
    return InfrastructureFactory.create_blob_storage(
        settings.blob_storage
    )


def get_vector_db(
    settings: Settings = Depends(get_settings)
) -> VectorDBBase:
    """Create vector DB from settings."""
    return InfrastructureFactory.create_vector_db(
        settings.vector_db
    )


# Use in routes
@router.post("/videos/ingest")
async def ingest_video(
    request: IngestRequest,
    blob_storage: BlobStorageBase = Depends(get_blob_storage),
    vector_db: VectorDBBase = Depends(get_vector_db),
    settings: Settings = Depends(get_settings)
):
    ...
```

---

## Validation

Settings are validated at startup:

```python
def validate_settings(settings: Settings) -> list[str]:
    """Validate settings and return list of errors."""
    errors = []

    # Check required API keys
    if not settings.transcription.api_key:
        errors.append("Transcription API key is required")

    if not settings.embeddings.text.api_key:
        errors.append("Text embedding API key is required")

    if not settings.llm.api_key:
        errors.append("LLM API key is required")

    # Check blob storage credentials
    if not settings.blob_storage.access_key:
        errors.append("Blob storage access key is required")

    # Check document DB credentials
    if not settings.document_db.password:
        errors.append("Document DB password is required")

    return errors


# In main.py
@app.on_event("startup")
async def startup():
    settings = get_settings()
    errors = validate_settings(settings)
    if errors:
        for error in errors:
            logger.error(f"Configuration error: {error}")
        raise RuntimeError("Invalid configuration")
```

---

## Secret Management (Production)

For production, use proper secret management:

### Kubernetes Secrets

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: youtube-rag-secrets
type: Opaque
stringData:
  YOUTUBE_RAG__BLOB_STORAGE__ACCESS_KEY: "..."
  YOUTUBE_RAG__BLOB_STORAGE__SECRET_KEY: "..."
  YOUTUBE_RAG__DOCUMENT_DB__PASSWORD: "..."
  YOUTUBE_RAG__TRANSCRIPTION__API_KEY: "..."
  YOUTUBE_RAG__EMBEDDINGS__TEXT__API_KEY: "..."
  YOUTUBE_RAG__LLM__API_KEY: "..."
```

### External Secrets Operator

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: youtube-rag-secrets
spec:
  secretStoreRef:
    kind: ClusterSecretStore
    name: vault-backend
  target:
    name: youtube-rag-secrets
  data:
    - secretKey: YOUTUBE_RAG__LLM__API_KEY
      remoteRef:
        key: youtube-rag/prod
        property: openai_api_key
```
