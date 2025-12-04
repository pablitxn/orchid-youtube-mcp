# YouTube RAG Server

## Project Overview

**Name:** youtube-rag-server
**Version:** 0.1.0
**Status:** In Development

### Goal

MCP Server + OpenAPI Plugin that enables LLM agents to index and query YouTube video content in a **multimodal** fashion (text, audio, frames, video), citing sources with **temporal precision**.

### Key Features

- **Multimodal Ingestion**: Download YouTube videos, extract transcriptions (Whisper), frames, and audio segments
- **Vector Indexing**: Text embeddings (OpenAI/Azure) and image embeddings (CLIP) stored in Qdrant
- **Semantic Queries**: RAG over video content with precise source citation
- **Temporal Citation**: Each response includes exact timestamps and access to original artifacts
- **Dual Exposure**: MCP server for agents + OpenAPI REST for direct integration

### Use Cases

1. **Content Research**: An agent can ingest an educational video and answer questions citing the exact minute
2. **Interview Analysis**: Search for specific moments where particular topics are discussed
3. **Summary Creation**: Generate summaries with navigable temporal references
4. **Fact-checking**: Verify claims by citing the original visual/audio source

### Tech Stack

| Component | Technology |
|-----------|------------|
| **Runtime** | Python 3.11+ |
| **API Framework** | FastAPI |
| **Blob Storage** | MinIO (dev) / Cloud Storage (prod) |
| **Vector DB** | Qdrant |
| **Document DB** | MongoDB |
| **Transcription** | Cloud Service (TBD) |
| **Text Embeddings** | Cloud Service (TBD) |
| **Image Embeddings** | Cloud Service (TBD) |
| **LLM** | Cloud Service (TBD) |
| **Observability** | Structured Logging → Loki |
| **Deployment** | Kubernetes + ArgoCD |

### Documentation Index

| Document | Description |
|----------|-------------|
| [01-ARCHITECTURE.md](./01-ARCHITECTURE.md) | Detailed system architecture |
| [02-DOMAIN-MODELS.md](./02-DOMAIN-MODELS.md) | Domain models and entities |
| [03-API-TOOLS.md](./03-API-TOOLS.md) | MCP Tools and REST endpoints specification |
| [04-INFRASTRUCTURE.md](./04-INFRASTRUCTURE.md) | Infrastructure services and providers |
| [05-CONFIGURATION.md](./05-CONFIGURATION.md) | Configuration system |
| [06-DEPLOYMENT.md](./06-DEPLOYMENT.md) | Deployment strategy |
| [07-IMPLEMENTATION-TASKS.md](./07-IMPLEMENTATION-TASKS.md) | Implementation task breakdown |

### Quick Start (TODO)

```bash
# Clone the repository
git clone <repo-url>
cd youtube-rag-server

# Install dependencies
poetry install

# Start local services
docker-compose up -d

# Run the server
poetry run uvicorn src.api.main:app --reload
```

### Project Structure

```
youtube-rag-server/
├── pyproject.toml              # Poetry configuration
├── docker-compose.yml          # Dev environment
├── config/                     # Configuration files
├── k8s/                        # Kubernetes manifests
├── src/
│   ├── commons/                # Shared package (future separate repo)
│   ├── domain/                 # Domain models
│   ├── application/            # Services and pipelines
│   ├── infrastructure/         # Infrastructure implementations
│   └── api/                    # FastAPI + MCP server
├── tests/                      # Unit, integration, e2e
└── docs/                       # Documentation
```

### Pending Decisions

- [ ] Specific provider for transcription (Whisper API, Deepgram, AssemblyAI, etc.)
- [ ] Specific provider for text embeddings
- [ ] Specific provider for image embeddings
- [ ] Specific provider for query LLM
- [ ] Blob storage strategy in production (S3, GCS, Azure Blob)
