# Data Transfer Objects (DTOs)

DTOs define the data contracts between the API and Application layers. They are Pydantic models that handle validation, serialization, and documentation.

**Source**: `src/application/dtos/`

## Overview

```
src/application/dtos/
├── __init__.py
├── ingestion.py    # Video ingestion DTOs
└── query.py        # Video query DTOs
```

## Ingestion DTOs

**Source**: `src/application/dtos/ingestion.py`

### ProcessingStep

Enumeration of individual steps in the ingestion pipeline.

```python
class ProcessingStep(str, Enum):
    """Individual steps in the ingestion pipeline."""

    VALIDATING = "validating"
    DOWNLOADING = "downloading"
    TRANSCRIBING = "transcribing"
    EXTRACTING_FRAMES = "extracting_frames"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    STORING = "storing"
    COMPLETED = "completed"
    FAILED = "failed"
```

### IngestionStatus

Overall ingestion status.

```python
class IngestionStatus(str, Enum):
    """Overall ingestion status."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
```

### IngestVideoRequest

Request to ingest a YouTube video.

```python
class IngestVideoRequest(BaseModel):
    """Request to ingest a YouTube video."""

    url: str = Field(
        description="YouTube video URL to ingest"
    )
    language_hint: str | None = Field(
        default=None,
        description="ISO language code hint for transcription (e.g., 'en', 'es')"
    )
    extract_frames: bool = Field(
        default=True,
        description="Whether to extract video frames for visual analysis"
    )
    extract_audio_chunks: bool = Field(
        default=False,
        description="Whether to create separate audio chunks"
    )
    extract_video_chunks: bool = Field(
        default=False,
        description="Whether to create video segment chunks for multimodal analysis"
    )
    max_resolution: int = Field(
        default=720,
        ge=144,
        le=2160,
        description="Maximum video resolution to download"
    )
```

#### Example

```python
request = IngestVideoRequest(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    language_hint="en",
    extract_frames=True,
    extract_audio_chunks=False,
    extract_video_chunks=False,
    max_resolution=720,
)
```

### IngestionProgress

Progress information for an ongoing ingestion.

```python
class IngestionProgress(BaseModel):
    """Progress information for an ongoing ingestion."""

    current_step: ProcessingStep = Field(
        description="Current processing step"
    )
    step_progress: float = Field(
        ge=0.0, le=1.0,
        description="Progress within current step (0.0 to 1.0)"
    )
    overall_progress: float = Field(
        ge=0.0, le=1.0,
        description="Overall ingestion progress (0.0 to 1.0)"
    )
    message: str = Field(
        description="Human-readable progress message"
    )
    started_at: datetime = Field(
        description="When ingestion started"
    )
    estimated_remaining_seconds: int | None = Field(
        default=None,
        description="Estimated seconds remaining"
    )
```

#### Example

```python
progress = IngestionProgress(
    current_step=ProcessingStep.TRANSCRIBING,
    step_progress=0.5,
    overall_progress=0.3,
    message="Transcribing audio...",
    started_at=datetime.now(UTC),
    estimated_remaining_seconds=120,
)
```

### IngestVideoResponse

Response from video ingestion.

```python
class IngestVideoResponse(BaseModel):
    """Response from video ingestion."""

    video_id: str = Field(
        description="Internal UUID for the ingested video"
    )
    youtube_id: str = Field(
        description="YouTube video ID"
    )
    title: str = Field(
        description="Video title"
    )
    duration_seconds: int = Field(
        description="Video duration in seconds"
    )
    status: IngestionStatus = Field(
        description="Current ingestion status"
    )
    progress: IngestionProgress | None = Field(
        default=None,
        description="Progress details if still processing"
    )
    error_message: str | None = Field(
        default=None,
        description="Error details if failed"
    )
    chunk_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Number of chunks created by modality"
    )
    created_at: datetime = Field(
        description="When ingestion was initiated"
    )
```

#### Example JSON Response

```json
{
  "video_id": "550e8400-e29b-41d4-a716-446655440000",
  "youtube_id": "dQw4w9WgXcQ",
  "title": "Rick Astley - Never Gonna Give You Up",
  "duration_seconds": 213,
  "status": "completed",
  "progress": null,
  "error_message": null,
  "chunk_counts": {
    "transcript": 42,
    "frame": 85,
    "audio": 0,
    "video": 0
  },
  "created_at": "2024-01-15T10:30:00Z"
}
```

---

## Query DTOs

**Source**: `src/application/dtos/query.py`

### QueryModality

Modalities available for querying.

```python
class QueryModality(str, Enum):
    """Modalities available for querying."""

    TRANSCRIPT = "transcript"
    FRAME = "frame"
    AUDIO = "audio"
    VIDEO = "video"
```

### TimestampRangeDTO

Timestamp range in a video.

```python
class TimestampRangeDTO(BaseModel):
    """Timestamp range in a video."""

    start_time: float = Field(
        ge=0,
        description="Start time in seconds"
    )
    end_time: float = Field(
        ge=0,
        description="End time in seconds"
    )
    display: str = Field(
        description="Human-readable time range"
    )
```

#### Example

```python
timestamp = TimestampRangeDTO(
    start_time=125.5,
    end_time=155.0,
    display="02:05 - 02:35"
)
```

### CitationDTO

A source citation for query results.

```python
class CitationDTO(BaseModel):
    """A source citation for query results."""

    id: str = Field(
        description="Citation identifier"
    )
    modality: QueryModality = Field(
        description="Type of source material"
    )
    timestamp_range: TimestampRangeDTO = Field(
        description="Location in video"
    )
    content_preview: str = Field(
        description="Preview of cited content"
    )
    relevance_score: float = Field(
        ge=0.0, le=1.0,
        description="How relevant this citation is to the query"
    )
    youtube_url: str | None = Field(
        default=None,
        description="Direct YouTube link with timestamp"
    )
    source_url: str | None = Field(
        default=None,
        description="Presigned URL for source artifact"
    )
```

#### Example JSON

```json
{
  "id": "chunk_550e8400",
  "modality": "transcript",
  "timestamp_range": {
    "start_time": 125.5,
    "end_time": 155.0,
    "display": "02:05 - 02:35"
  },
  "content_preview": "In this section, we'll discuss the main concepts...",
  "relevance_score": 0.92,
  "youtube_url": "https://youtube.com/watch?v=abc123&t=125",
  "source_url": null
}
```

### QueryMetadata

Metadata about the query execution.

```python
class QueryMetadata(BaseModel):
    """Metadata about the query execution."""

    video_id: str = Field(
        description="ID of the queried video"
    )
    video_title: str = Field(
        description="Title of the queried video"
    )
    modalities_searched: list[QueryModality] = Field(
        description="Which modalities were searched"
    )
    chunks_analyzed: int = Field(
        description="Number of chunks analyzed"
    )
    processing_time_ms: int = Field(
        description="Total processing time in milliseconds"
    )
```

### QueryVideoRequest

Request to query a video's content.

```python
class QueryVideoRequest(BaseModel):
    """Request to query a video's content."""

    query: str = Field(
        min_length=1,
        max_length=1000,
        description="Natural language question about the video"
    )
    modalities: list[QueryModality] = Field(
        default=[QueryModality.TRANSCRIPT, QueryModality.FRAME],
        description="Which modalities to search across"
    )
    max_citations: int = Field(
        default=5,
        ge=1, le=20,
        description="Maximum number of citations to return"
    )
    include_reasoning: bool = Field(
        default=True,
        description="Whether to include explanation of reasoning"
    )
    similarity_threshold: float = Field(
        default=0.7,
        ge=0.0, le=1.0,
        description="Minimum similarity score for results"
    )
```

#### Example

```python
request = QueryVideoRequest(
    query="What programming concepts are explained?",
    modalities=[QueryModality.TRANSCRIPT],
    max_citations=5,
    include_reasoning=True,
    similarity_threshold=0.7,
)
```

### QueryVideoResponse

Response from querying a video.

```python
class QueryVideoResponse(BaseModel):
    """Response from querying a video."""

    answer: str = Field(
        description="Answer to the query based on video content"
    )
    reasoning: str | None = Field(
        default=None,
        description="Explanation of how the answer was derived"
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence score for the answer"
    )
    citations: list[CitationDTO] = Field(
        default_factory=list,
        description="Source citations supporting the answer"
    )
    query_metadata: QueryMetadata = Field(
        description="Information about query execution"
    )
```

#### Example JSON Response

```json
{
  "answer": "The video covers Python basics including variables, functions, and classes.",
  "reasoning": "Based on transcript segments at 2:05, 5:30, and 8:15 which explicitly discuss these topics.",
  "confidence": 0.87,
  "citations": [
    {
      "id": "chunk_001",
      "modality": "transcript",
      "timestamp_range": {
        "start_time": 125,
        "end_time": 155,
        "display": "02:05 - 02:35"
      },
      "content_preview": "Let's start by understanding variables...",
      "relevance_score": 0.92,
      "youtube_url": "https://youtube.com/watch?v=abc123&t=125"
    }
  ],
  "query_metadata": {
    "video_id": "550e8400-e29b-41d4-a716-446655440000",
    "video_title": "Python Tutorial for Beginners",
    "modalities_searched": ["transcript"],
    "chunks_analyzed": 12,
    "processing_time_ms": 450
  }
}
```

### SourceArtifact

A source artifact with presigned URL.

```python
class SourceArtifact(BaseModel):
    """A source artifact with presigned URL."""

    type: str = Field(
        description="Artifact type (transcript_text, frame_image)"
    )
    url: str | None = Field(
        default=None,
        description="Presigned URL to access"
    )
    content: str | None = Field(
        default=None,
        description="Text content if applicable"
    )
```

### SourceDetail

Detailed source information for a citation.

```python
class SourceDetail(BaseModel):
    """Detailed source information for a citation."""

    citation_id: str = Field(
        description="Citation identifier"
    )
    modality: QueryModality = Field(
        description="Source modality"
    )
    timestamp_range: TimestampRangeDTO = Field(
        description="Time range in video"
    )
    artifacts: dict[str, SourceArtifact] = Field(
        default_factory=dict,
        description="Available artifacts by type"
    )
```

### GetSourcesRequest

Request to get source details for citations.

```python
class GetSourcesRequest(BaseModel):
    """Request to get source details for citations."""

    citation_ids: list[str] = Field(
        min_length=1,
        description="Citation IDs to retrieve sources for"
    )
    include_artifacts: list[str] = Field(
        default=["transcript_text", "thumbnail"],
        description="Which artifact types to include"
    )
    url_expiry_minutes: int = Field(
        default=60,
        ge=5, le=1440,
        description="How long presigned URLs should remain valid"
    )
```

### SourcesResponse

Response with detailed source information.

```python
class SourcesResponse(BaseModel):
    """Response with detailed source information."""

    sources: list[SourceDetail] = Field(
        description="Detailed source information"
    )
    expires_at: datetime = Field(
        description="When presigned URLs expire"
    )
```

---

## Validation Examples

Pydantic provides automatic validation:

```python
# Valid request
request = IngestVideoRequest(
    url="https://youtube.com/watch?v=abc123",
    max_resolution=720,
)

# Invalid - resolution out of range
try:
    request = IngestVideoRequest(
        url="https://youtube.com/watch?v=abc123",
        max_resolution=5000,  # Invalid: max is 2160
    )
except ValidationError as e:
    print(e)
    # max_resolution: Input should be less than or equal to 2160

# Invalid - query too short
try:
    request = QueryVideoRequest(query="")  # Invalid: min_length=1
except ValidationError as e:
    print(e)
    # query: String should have at least 1 character
```

## Serialization

DTOs serialize to JSON automatically:

```python
response = IngestVideoResponse(
    video_id="550e8400...",
    youtube_id="abc123",
    title="My Video",
    duration_seconds=300,
    status=IngestionStatus.COMPLETED,
    chunk_counts={"transcript": 10, "frame": 20},
    created_at=datetime.now(UTC),
)

# To JSON dict
json_dict = response.model_dump(mode="json")

# To JSON string
json_str = response.model_dump_json()
```
