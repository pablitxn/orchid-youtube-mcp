# Video Storage Service

The `VideoStorageService` manages all storage operations for video content, including blob storage for media files and document storage for metadata and chunks.

**Source**: `src/application/services/storage.py`

## Overview

The storage service provides:

- Video/audio/frame blob management
- Video metadata CRUD operations
- Chunk storage and retrieval by modality
- Presigned URL generation
- Complete video deletion

## Class Definition

```python
class VideoStorageService:
    """Manages storage of video content and metadata."""

    def __init__(
        self,
        blob_storage: BlobStorageBase,
        document_db: DocumentDBBase,
        blob_settings: BlobStorageSettings,
        doc_settings: DocumentDBSettings,
    ) -> None:
        ...
```

### Dependencies

| Dependency | Type | Purpose |
|------------|------|---------|
| `blob_storage` | `BlobStorageBase` | Store binary files (MinIO/S3) |
| `document_db` | `DocumentDBBase` | Store metadata (MongoDB) |
| `blob_settings` | `BlobStorageSettings` | Bucket configuration |
| `doc_settings` | `DocumentDBSettings` | Collection configuration |

### Bucket Structure

```
videos/          # Video and audio files
  {video_id}/
    video.mp4
    audio.mp3

frames/          # Extracted frames
  {video_id}/
    frames/
      frame_00000.jpg
      thumb_00000.jpg

chunks/          # Audio/video chunks
  {video_id}/
    audio/
    video/
```

### Collection Structure

```
videos                 # Video metadata
transcript_chunks      # Transcript chunk documents
frame_chunks          # Frame chunk documents
audio_chunks          # Audio chunk documents
video_chunks          # Video segment documents
```

## Methods

### Bucket Management

#### `ensure_buckets_exist()`

Ensure all required storage buckets exist.

```python
async def ensure_buckets_exist(self) -> None:
    """Ensure all required buckets exist."""
    for bucket in [self._videos_bucket, self._frames_bucket, self._chunks_bucket]:
        if not await self._blob.bucket_exists(bucket):
            await self._blob.create_bucket(bucket)
```

### Video Metadata Operations

#### `save_video_metadata()`

Save video metadata to document database.

```python
async def save_video_metadata(self, video: VideoMetadata) -> str:
    """Save video metadata to document database.

    Args:
        video: Video metadata to save.

    Returns:
        Document ID.
    """
```

#### Example

```python
from src.domain.models.video import VideoMetadata, VideoStatus

video = VideoMetadata(
    youtube_id="dQw4w9WgXcQ",
    youtube_url="https://youtube.com/watch?v=dQw4w9WgXcQ",
    title="Rick Astley - Never Gonna Give You Up",
    description="Official music video...",
    duration_seconds=213,
    channel_name="Rick Astley",
    status=VideoStatus.DOWNLOADING,
)

doc_id = await storage.save_video_metadata(video)
print(f"Saved video with ID: {doc_id}")
```

#### `update_video_metadata()`

Update existing video metadata.

```python
async def update_video_metadata(self, video: VideoMetadata) -> bool:
    """Update existing video metadata.

    Args:
        video: Updated video metadata.

    Returns:
        True if updated, False if not found.
    """
```

#### `get_video_metadata()`

Get video metadata by ID.

```python
async def get_video_metadata(self, video_id: str) -> VideoMetadata | None:
    """Get video metadata by ID.

    Args:
        video_id: Internal video UUID.

    Returns:
        Video metadata or None if not found.
    """
```

#### `get_video_by_youtube_id()`

Get video metadata by YouTube video ID.

```python
async def get_video_by_youtube_id(self, youtube_id: str) -> VideoMetadata | None:
    """Get video metadata by YouTube video ID.

    Args:
        youtube_id: YouTube video ID (11 characters).

    Returns:
        Video metadata or None if not found.
    """
```

#### `list_videos()`

List videos with optional filtering.

```python
async def list_videos(
    self,
    status: VideoStatus | None = None,
    skip: int = 0,
    limit: int = 20,
) -> list[VideoMetadata]:
    """List videos with optional filtering.

    Args:
        status: Optional status filter.
        skip: Number to skip.
        limit: Maximum to return.

    Returns:
        List of video metadata.
    """
```

#### Example

```python
from src.domain.models.video import VideoStatus

# List ready videos
ready_videos = await storage.list_videos(
    status=VideoStatus.READY,
    limit=10
)

for video in ready_videos:
    print(f"{video.title} - {video.duration_seconds}s")
```

#### `update_video_status()`

Update video processing status.

```python
async def update_video_status(
    self,
    video_id: str,
    status: VideoStatus,
    error_message: str | None = None,
) -> bool:
    """Update video processing status.

    Args:
        video_id: Internal video UUID.
        status: New status.
        error_message: Optional error message for FAILED status.

    Returns:
        True if updated.
    """
```

### Blob Storage Operations

#### `upload_video()`

Upload video file to blob storage.

```python
async def upload_video(
    self,
    video_id: str,
    video_path: Path,
    content_type: str = "video/mp4",
) -> str:
    """Upload video file to blob storage.

    Args:
        video_id: Internal video UUID.
        video_path: Local path to video file.
        content_type: MIME type.

    Returns:
        Blob path.
    """
```

#### Example

```python
from pathlib import Path

blob_path = await storage.upload_video(
    video_id="550e8400-e29b-41d4-a716-446655440000",
    video_path=Path("/tmp/download/video.mp4"),
)

print(f"Video uploaded to: {blob_path}")
# Output: Video uploaded to: 550e8400.../video.mp4
```

#### `upload_audio()`

Upload audio file to blob storage.

```python
async def upload_audio(
    self,
    video_id: str,
    audio_path: Path,
    content_type: str = "audio/mpeg",
) -> str:
    """Upload audio file to blob storage."""
```

#### `upload_frame()`

Upload frame image to blob storage.

```python
async def upload_frame(
    self,
    video_id: str,
    frame_path: Path,
    frame_number: int,
) -> tuple[str, str]:
    """Upload frame image to blob storage.

    Args:
        video_id: Internal video UUID.
        frame_path: Local path to frame image.
        frame_number: Frame sequence number.

    Returns:
        Tuple of (blob_path, thumbnail_path).
    """
```

#### Example

```python
blob_path, thumb_path = await storage.upload_frame(
    video_id="550e8400-e29b-41d4-a716-446655440000",
    frame_path=Path("/tmp/frames/frame_00042.jpg"),
    frame_number=42,
)

print(f"Frame: {blob_path}")
print(f"Thumbnail: {thumb_path}")
```

#### `get_presigned_url()`

Generate a presigned URL for blob access.

```python
async def get_presigned_url(
    self,
    bucket: str,
    path: str,
    expiry_seconds: int | None = None,
) -> str:
    """Generate a presigned URL for blob access.

    Args:
        bucket: Bucket name.
        path: Blob path.
        expiry_seconds: URL validity duration.

    Returns:
        Presigned URL string.
    """
```

#### Example

```python
# Generate URL valid for 1 hour
url = await storage.get_presigned_url(
    bucket="frames",
    path="550e8400.../frames/frame_00042.jpg",
    expiry_seconds=3600,
)

print(f"Access frame at: {url}")
```

#### `delete_video_blobs()`

Delete all blobs for a video.

```python
async def delete_video_blobs(self, video_id: str) -> int:
    """Delete all blobs for a video.

    Args:
        video_id: Internal video UUID.

    Returns:
        Number of blobs deleted.
    """
```

### Chunk Storage Operations

#### `save_chunks()`

Save chunks to document database.

```python
async def save_chunks(self, chunks: list[AnyChunk]) -> list[str]:
    """Save chunks to document database.

    Args:
        chunks: Chunks to save.

    Returns:
        List of document IDs.
    """
```

Chunks are automatically routed to the correct collection based on modality:

```python
# Group by modality for batch insert
by_modality: dict[Modality, list[AnyChunk]] = {}
for chunk in chunks:
    if chunk.modality not in by_modality:
        by_modality[chunk.modality] = []
    by_modality[chunk.modality].append(chunk)

# Insert each group
for modality, modality_chunks in by_modality.items():
    collection = self._get_chunk_collection(modality)
    await self._doc_db.insert_many(collection, docs)
```

#### Example

```python
from src.domain.models.chunk import TranscriptChunk, FrameChunk

chunks = [
    TranscriptChunk(...),
    TranscriptChunk(...),
    FrameChunk(...),
]

ids = await storage.save_chunks(chunks)
print(f"Saved {len(ids)} chunks")
```

#### `get_chunks_for_video()`

Get all chunks for a video.

```python
async def get_chunks_for_video(
    self,
    video_id: str,
    modality: Modality | None = None,
) -> list[AnyChunk]:
    """Get all chunks for a video.

    Args:
        video_id: Internal video UUID.
        modality: Optional modality filter.

    Returns:
        List of chunks.
    """
```

#### Example

```python
from src.domain.models.chunk import Modality

# Get all transcript chunks
transcript_chunks = await storage.get_chunks_for_video(
    video_id="550e8400-e29b-41d4-a716-446655440000",
    modality=Modality.TRANSCRIPT,
)

# Get all chunks (any modality)
all_chunks = await storage.get_chunks_for_video(
    video_id="550e8400-e29b-41d4-a716-446655440000",
)

print(f"Transcript: {len(transcript_chunks)}")
print(f"Total: {len(all_chunks)}")
```

#### `get_chunk_by_id()`

Get a specific chunk by ID.

```python
async def get_chunk_by_id(
    self,
    chunk_id: str,
    modality: Modality,
) -> AnyChunk | None:
    """Get a specific chunk by ID.

    Args:
        chunk_id: Chunk UUID.
        modality: Chunk modality.

    Returns:
        Chunk or None if not found.
    """
```

#### `delete_chunks_for_video()`

Delete all chunks for a video.

```python
async def delete_chunks_for_video(self, video_id: str) -> int:
    """Delete all chunks for a video.

    Args:
        video_id: Internal video UUID.

    Returns:
        Number of chunks deleted.
    """
```

### Complete Video Deletion

#### `delete_video_completely()`

Delete a video and all associated data.

```python
async def delete_video_completely(self, video_id: str) -> dict[str, int]:
    """Delete a video and all associated data.

    Args:
        video_id: Internal video UUID.

    Returns:
        Dictionary with deletion counts.
    """
```

#### Example

```python
results = await storage.delete_video_completely(
    video_id="550e8400-e29b-41d4-a716-446655440000"
)

print(f"Deleted blobs: {results['blobs']}")
print(f"Deleted chunks: {results['chunks']}")
print(f"Deleted metadata: {results['metadata']}")
```

## Modality Routing

The service automatically routes chunks to the correct collection:

```python
def _get_chunk_collection(self, modality: Modality) -> str:
    """Get collection name for chunk modality."""
    mapping = {
        Modality.TRANSCRIPT: self._transcript_chunks_collection,
        Modality.FRAME: self._frame_chunks_collection,
        Modality.AUDIO: self._audio_chunks_collection,
        Modality.VIDEO: self._video_chunks_collection,
    }
    return mapping[modality]
```

## Document to Chunk Conversion

```python
def _doc_to_chunk(
    self,
    doc: dict[str, Any],
    modality: Modality,
) -> AnyChunk | None:
    """Convert document to appropriate chunk type."""
    if modality == Modality.TRANSCRIPT:
        return TranscriptChunk(**doc)
    elif modality == Modality.FRAME:
        return FrameChunk(**doc)
    elif modality == Modality.AUDIO:
        return AudioChunk(**doc)
    elif modality == Modality.VIDEO:
        return VideoChunk(**doc)
    return None
```

## Configuration

### Blob Storage Settings

```json
{
  "blob_storage": {
    "buckets": {
      "videos": "yt-rag-videos",
      "frames": "yt-rag-frames",
      "chunks": "yt-rag-chunks"
    },
    "presigned_url_expiry_seconds": 3600
  }
}
```

### Document DB Settings

```json
{
  "document_db": {
    "collections": {
      "videos": "videos",
      "transcript_chunks": "transcript_chunks",
      "frame_chunks": "frame_chunks",
      "audio_chunks": "audio_chunks",
      "video_chunks": "video_chunks"
    }
  }
}
```

## Usage with Other Services

The storage service is typically used by other application services:

```python
class VideoIngestionService:
    def __init__(self, storage: VideoStorageService, ...):
        self._storage = storage

    async def ingest(self, request: IngestVideoRequest):
        # Save initial metadata
        await self._storage.save_video_metadata(video)

        # Upload video file
        await self._storage.upload_video(video.id, video_path)

        # Save chunks
        await self._storage.save_chunks(transcript_chunks + frame_chunks)

        # Update status
        await self._storage.update_video_status(video.id, VideoStatus.READY)
```

## Error Handling

```python
try:
    video = await storage.get_video_metadata(video_id)
    if not video:
        raise ValueError(f"Video not found: {video_id}")

    chunks = await storage.get_chunks_for_video(video_id)

except Exception as e:
    logger.error(f"Storage error: {e}")
    raise
```
