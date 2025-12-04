# API & Tools Specification

## Overview

The YouTube RAG Server exposes its functionality through two interfaces:
1. **MCP Server**: For AI agent integration via the Model Context Protocol
2. **OpenAPI REST**: For direct HTTP integration and as a ChatGPT/Copilot plugin

Both interfaces expose the same core functionality through the Application Layer services.

---

## MCP Tools

The Model Context Protocol (MCP) tools are designed for AI agents to discover and invoke programmatically.

### Tool: `ingest_video`

Downloads, processes, and indexes a YouTube video for semantic search.

```json
{
  "name": "ingest_video",
  "description": "Download and index a YouTube video for semantic search. Extracts transcript, frames, audio, and video segments for multimodal querying.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "youtube_url": {
        "type": "string",
        "description": "Full YouTube URL (supports youtube.com/watch, youtu.be, shorts)"
      },
      "options": {
        "type": "object",
        "description": "Optional processing configuration",
        "properties": {
          "extract_frames": {
            "type": "boolean",
            "default": true,
            "description": "Whether to extract video frames"
          },
          "extract_audio_chunks": {
            "type": "boolean",
            "default": false,
            "description": "Whether to create audio-only chunks"
          },
          "extract_video_chunks": {
            "type": "boolean",
            "default": true,
            "description": "Whether to create video segment chunks"
          },
          "language_hint": {
            "type": "string",
            "description": "Expected language (ISO 639-1) for transcription"
          },
          "priority": {
            "type": "string",
            "enum": ["low", "normal", "high"],
            "default": "normal",
            "description": "Processing priority"
          }
        }
      }
    },
    "required": ["youtube_url"]
  }
}
```

**Response:**
```json
{
  "video_id": "uuid-here",
  "youtube_id": "dQw4w9WgXcQ",
  "title": "Video Title",
  "duration_seconds": 212,
  "status": "processing",
  "estimated_completion_seconds": 120,
  "message": "Video ingestion started. Use get_ingestion_status to track progress."
}
```

---

### Tool: `get_ingestion_status`

Check the processing status of an ingested video.

```json
{
  "name": "get_ingestion_status",
  "description": "Get the current processing status of a video ingestion job.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "video_id": {
        "type": "string",
        "description": "The video ID returned from ingest_video"
      }
    },
    "required": ["video_id"]
  }
}
```

**Response:**
```json
{
  "video_id": "uuid-here",
  "status": "transcribing",
  "progress": {
    "download": "completed",
    "transcription": "in_progress",
    "frame_extraction": "pending",
    "video_chunking": "pending",
    "embedding": "pending"
  },
  "progress_percent": 35,
  "stats": {
    "transcript_chunks": 0,
    "frame_chunks": 0,
    "video_chunks": 0,
    "audio_chunks": 0
  },
  "errors": [],
  "started_at": "2024-01-15T10:30:00Z",
  "estimated_completion": "2024-01-15T10:35:00Z"
}
```

---

### Tool: `query_video`

Ask questions about the content of an indexed video.

```json
{
  "name": "query_video",
  "description": "Query the content of an indexed YouTube video using natural language. Returns an answer with citations to specific timestamps.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "video_id": {
        "type": "string",
        "description": "The video ID to query"
      },
      "query": {
        "type": "string",
        "description": "Natural language question about the video content"
      },
      "modalities": {
        "type": "array",
        "items": {
          "type": "string",
          "enum": ["transcript", "frame", "audio", "video"]
        },
        "default": ["transcript", "frame"],
        "description": "Which modalities to search across"
      },
      "max_citations": {
        "type": "integer",
        "default": 5,
        "minimum": 1,
        "maximum": 20,
        "description": "Maximum number of source citations to return"
      },
      "include_reasoning": {
        "type": "boolean",
        "default": true,
        "description": "Whether to include reasoning explanation"
      }
    },
    "required": ["video_id", "query"]
  }
}
```

**Response:**
```json
{
  "answer": "The speaker discusses the importance of testing at minute 5:30, emphasizing that unit tests should cover edge cases.",
  "reasoning": "Based on transcript chunks from 5:15-6:00 and a visual diagram shown at 5:45, the speaker makes a clear argument about testing practices.",
  "confidence": 0.89,
  "citations": [
    {
      "id": "cite-1",
      "modality": "transcript",
      "timestamp_range": {
        "start_time": 315.0,
        "end_time": 360.0,
        "display": "05:15 - 06:00"
      },
      "content_preview": "...and that's why unit tests are so important. You need to cover edge cases...",
      "relevance_score": 0.92,
      "youtube_url": "https://youtube.com/watch?v=xxx&t=315"
    },
    {
      "id": "cite-2",
      "modality": "frame",
      "timestamp_range": {
        "start_time": 345.0,
        "end_time": 347.0,
        "display": "05:45 - 05:47"
      },
      "content_preview": "Diagram showing test pyramid with unit tests at the base",
      "relevance_score": 0.85,
      "source_url": "https://presigned-url-to-frame.jpg"
    }
  ],
  "query_metadata": {
    "video_id": "uuid-here",
    "video_title": "Testing Best Practices",
    "modalities_searched": ["transcript", "frame"],
    "chunks_analyzed": 45,
    "processing_time_ms": 1250
  }
}
```

---

### Tool: `get_sources`

Retrieve detailed source artifacts for citations.

```json
{
  "name": "get_sources",
  "description": "Get detailed source artifacts (frames, audio clips, video segments) for specific citations.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "video_id": {
        "type": "string",
        "description": "The video ID"
      },
      "citation_ids": {
        "type": "array",
        "items": {
          "type": "string"
        },
        "description": "List of citation IDs to retrieve sources for"
      },
      "include_artifacts": {
        "type": "array",
        "items": {
          "type": "string",
          "enum": ["transcript_text", "frame_image", "audio_clip", "video_segment", "thumbnail"]
        },
        "default": ["transcript_text", "thumbnail"],
        "description": "Which artifact types to include"
      },
      "url_expiry_minutes": {
        "type": "integer",
        "default": 60,
        "minimum": 5,
        "maximum": 1440,
        "description": "How long presigned URLs should remain valid"
      }
    },
    "required": ["video_id", "citation_ids"]
  }
}
```

**Response:**
```json
{
  "sources": [
    {
      "citation_id": "cite-1",
      "modality": "transcript",
      "timestamp_range": {
        "start_time": 315.0,
        "end_time": 360.0
      },
      "artifacts": {
        "transcript_text": "Full transcript text for this segment...",
        "word_timestamps": [
          {"word": "and", "start": 315.0, "end": 315.2},
          {"word": "that's", "start": 315.2, "end": 315.5}
        ],
        "thumbnail": "https://presigned-url/thumbnail.jpg"
      }
    },
    {
      "citation_id": "cite-2",
      "modality": "frame",
      "timestamp_range": {
        "start_time": 345.0,
        "end_time": 347.0
      },
      "artifacts": {
        "frame_image": "https://presigned-url/frame-345.jpg",
        "thumbnail": "https://presigned-url/thumb-345.jpg"
      }
    }
  ],
  "expires_at": "2024-01-15T11:30:00Z"
}
```

---

### Tool: `list_videos`

List all indexed videos with optional filtering.

```json
{
  "name": "list_videos",
  "description": "List all indexed videos with optional filtering and pagination.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "filters": {
        "type": "object",
        "properties": {
          "status": {
            "type": "array",
            "items": {
              "type": "string",
              "enum": ["pending", "downloading", "transcribing", "extracting", "embedding", "ready", "failed"]
            },
            "description": "Filter by processing status"
          },
          "channel_name": {
            "type": "string",
            "description": "Filter by YouTube channel name (partial match)"
          },
          "title_contains": {
            "type": "string",
            "description": "Filter by title (partial match)"
          },
          "min_duration_seconds": {
            "type": "integer",
            "description": "Minimum video duration"
          },
          "max_duration_seconds": {
            "type": "integer",
            "description": "Maximum video duration"
          },
          "created_after": {
            "type": "string",
            "format": "date-time",
            "description": "Filter by creation date"
          }
        }
      },
      "pagination": {
        "type": "object",
        "properties": {
          "page": {
            "type": "integer",
            "default": 1,
            "minimum": 1
          },
          "page_size": {
            "type": "integer",
            "default": 20,
            "minimum": 1,
            "maximum": 100
          }
        }
      },
      "sort_by": {
        "type": "string",
        "enum": ["created_at", "title", "duration", "channel_name"],
        "default": "created_at"
      },
      "sort_order": {
        "type": "string",
        "enum": ["asc", "desc"],
        "default": "desc"
      }
    }
  }
}
```

**Response:**
```json
{
  "videos": [
    {
      "id": "uuid-1",
      "youtube_id": "dQw4w9WgXcQ",
      "title": "Video Title",
      "channel_name": "Channel Name",
      "duration_seconds": 212,
      "status": "ready",
      "thumbnail_url": "https://...",
      "created_at": "2024-01-15T10:00:00Z",
      "stats": {
        "transcript_chunks": 15,
        "frame_chunks": 106,
        "video_chunks": 8,
        "audio_chunks": 4
      }
    }
  ],
  "pagination": {
    "page": 1,
    "page_size": 20,
    "total_items": 45,
    "total_pages": 3
  }
}
```

---

### Tool: `delete_video`

Delete a video and all its associated data.

```json
{
  "name": "delete_video",
  "description": "Delete an indexed video and all its associated data (chunks, embeddings, artifacts).",
  "inputSchema": {
    "type": "object",
    "properties": {
      "video_id": {
        "type": "string",
        "description": "The video ID to delete"
      },
      "confirm": {
        "type": "boolean",
        "description": "Must be true to confirm deletion"
      }
    },
    "required": ["video_id", "confirm"]
  }
}
```

**Response:**
```json
{
  "success": true,
  "video_id": "uuid-here",
  "deleted_artifacts": {
    "video_file": true,
    "audio_file": true,
    "transcript_chunks": 15,
    "frame_chunks": 106,
    "video_chunks": 8,
    "audio_chunks": 4,
    "embeddings": 133,
    "blob_storage_mb_freed": 256.5
  },
  "message": "Video and all associated data deleted successfully"
}
```

---

## OpenAPI REST Endpoints

The REST API mirrors the MCP tools with standard HTTP conventions.

### Base URL

```
https://api.youtube-rag.example.com/v1
```

### Authentication

```
Authorization: Bearer <api_key>
```

### Endpoints

#### POST /videos/ingest

Ingest a new YouTube video.

**Request:**
```http
POST /v1/videos/ingest
Content-Type: application/json
Authorization: Bearer <api_key>

{
  "youtube_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
  "options": {
    "extract_frames": true,
    "extract_video_chunks": true
  }
}
```

**Response:** `202 Accepted`
```json
{
  "video_id": "uuid-here",
  "status": "processing",
  "links": {
    "self": "/v1/videos/uuid-here",
    "status": "/v1/videos/uuid-here/status"
  }
}
```

---

#### GET /videos/{video_id}/status

Get ingestion status.

**Request:**
```http
GET /v1/videos/uuid-here/status
Authorization: Bearer <api_key>
```

**Response:** `200 OK`
```json
{
  "video_id": "uuid-here",
  "status": "ready",
  "progress_percent": 100,
  "stats": { ... }
}
```

---

#### POST /videos/{video_id}/query

Query video content.

**Request:**
```http
POST /v1/videos/uuid-here/query
Content-Type: application/json
Authorization: Bearer <api_key>

{
  "query": "What does the speaker say about testing?",
  "modalities": ["transcript", "frame"],
  "max_citations": 5
}
```

**Response:** `200 OK`
```json
{
  "answer": "...",
  "citations": [...],
  "query_metadata": {...}
}
```

---

#### GET /videos/{video_id}/sources

Get source artifacts.

**Request:**
```http
GET /v1/videos/uuid-here/sources?citation_ids=cite-1,cite-2&include_artifacts=transcript_text,frame_image
Authorization: Bearer <api_key>
```

**Response:** `200 OK`
```json
{
  "sources": [...],
  "expires_at": "..."
}
```

---

#### GET /videos

List videos.

**Request:**
```http
GET /v1/videos?status=ready&page=1&page_size=20
Authorization: Bearer <api_key>
```

**Response:** `200 OK`
```json
{
  "videos": [...],
  "pagination": {...}
}
```

---

#### DELETE /videos/{video_id}

Delete a video.

**Request:**
```http
DELETE /v1/videos/uuid-here
Authorization: Bearer <api_key>
X-Confirm-Delete: true
```

**Response:** `200 OK`
```json
{
  "success": true,
  "deleted_artifacts": {...}
}
```

---

## Error Responses

### Standard Error Format

```json
{
  "error": {
    "code": "VIDEO_NOT_FOUND",
    "message": "Video with ID 'uuid-here' was not found",
    "details": {
      "video_id": "uuid-here"
    },
    "request_id": "req-uuid",
    "documentation_url": "https://docs.example.com/errors/VIDEO_NOT_FOUND"
  }
}
```

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `VALIDATION_ERROR` | 400 | Invalid request parameters |
| `INVALID_YOUTUBE_URL` | 400 | YouTube URL is invalid or unsupported |
| `UNAUTHORIZED` | 401 | Missing or invalid API key |
| `FORBIDDEN` | 403 | API key lacks required permissions |
| `VIDEO_NOT_FOUND` | 404 | Video ID does not exist |
| `VIDEO_NOT_READY` | 409 | Video is still processing |
| `VIDEO_FAILED` | 409 | Video processing failed |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Unexpected server error |
| `SERVICE_UNAVAILABLE` | 503 | Dependent service unavailable |

---

## Rate Limiting

| Endpoint | Rate Limit | Burst |
|----------|------------|-------|
| `POST /videos/ingest` | 10/hour | 3 |
| `POST /videos/{id}/query` | 100/minute | 20 |
| `GET /videos/{id}/sources` | 200/minute | 50 |
| `GET /videos` | 60/minute | 10 |
| `DELETE /videos/{id}` | 30/hour | 5 |

Rate limit headers:
```http
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 95
X-RateLimit-Reset: 1705320000
```

---

## Webhooks (Future Enhancement)

For long-running ingestion jobs, webhooks can notify when processing completes:

```json
{
  "event": "video.ingestion.completed",
  "video_id": "uuid-here",
  "status": "ready",
  "timestamp": "2024-01-15T10:35:00Z",
  "stats": {
    "transcript_chunks": 15,
    "frame_chunks": 106,
    "video_chunks": 8
  }
}
```

---

## OpenAPI Specification

The full OpenAPI 3.0 specification is available at:
- **JSON:** `GET /openapi.json`
- **YAML:** `GET /openapi.yaml`
- **Swagger UI:** `GET /docs`
- **ReDoc:** `GET /redoc`
