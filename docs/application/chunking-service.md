# Chunking Service

The `ChunkingService` creates content chunks from different media types, handling transcript segmentation, frame extraction, audio splitting, and video segment creation.

**Source**: `src/application/services/chunking.py`

## Overview

The chunking service transforms raw media into searchable chunks:

- **Transcript chunks**: Text segments with overlap for context preservation
- **Frame chunks**: Images extracted at regular intervals
- **Audio chunks**: Audio segments (for future audio embedding)
- **Video chunks**: Short video clips for multimodal LLM analysis

## Class Definition

```python
class ChunkingService:
    """Service for creating chunks from different media types."""

    def __init__(
        self,
        frame_extractor: FrameExtractorBase,
        video_chunker: VideoChunkerBase | None = None,
        settings: ChunkingSettings | None = None,
    ) -> None:
        ...
```

### Dependencies

| Dependency | Type | Purpose |
|------------|------|---------|
| `frame_extractor` | `FrameExtractorBase` | Extract frames using FFmpeg |
| `video_chunker` | `VideoChunkerBase` | Create video segments (optional) |
| `settings` | `ChunkingSettings` | Chunking configuration |

## Result Type

```python
@dataclass
class ChunkingResult:
    """Result from chunking operations."""

    transcript_chunks: list[TranscriptChunk]
    frame_chunks: list[FrameChunk]
    audio_chunks: list[AudioChunk]
    video_chunks: list[VideoChunk]
```

## Methods

### `create_transcript_chunks()`

Create transcript chunks from transcription segments with configurable overlap.

```python
def create_transcript_chunks(
    self,
    segments: list[TranscriptionSegment],
    video_id: str,
    language: str,
) -> list[TranscriptChunk]:
    """Create transcript chunks from transcription segments.

    Args:
        segments: Transcription segments with word timestamps.
        video_id: Parent video ID.
        language: Detected language code.

    Returns:
        List of transcript chunks.
    """
```

#### Chunking Algorithm

The algorithm creates overlapping windows to preserve context across chunk boundaries:

```
Input: Transcription segments with timestamps
Settings: chunk_seconds=30, overlap_seconds=5

Timeline:
0s          30s         60s         90s
|-----------|-----------|-----------|
   Chunk 1
|-----------|
        |-----------|
           Chunk 2 (starts at 25s, overlaps 5s)
                |-----------|
                   Chunk 3 (starts at 55s)
```

#### Example

```python
from src.infrastructure.transcription.base import TranscriptionSegment

# Transcription segments from Whisper
segments = [
    TranscriptionSegment(
        text="Hello, welcome to this video.",
        start_time=0.0,
        end_time=3.5,
        confidence=0.95,
        words=[...],
    ),
    TranscriptionSegment(
        text="Today we'll discuss Python.",
        start_time=3.5,
        end_time=6.2,
        confidence=0.92,
        words=[...],
    ),
    # ... more segments
]

# Create chunks
chunks = service.create_transcript_chunks(
    segments=segments,
    video_id="550e8400-e29b-41d4-a716-446655440000",
    language="en",
)

for chunk in chunks:
    print(f"[{chunk.start_time:.1f}s - {chunk.end_time:.1f}s]")
    print(f"  Text: {chunk.text[:50]}...")
    print(f"  Words: {len(chunk.word_timestamps)}")
    print(f"  Confidence: {chunk.confidence:.2f}")
```

#### Output

```
[0.0s - 28.5s]
  Text: Hello, welcome to this video. Today we'll discuss...
  Words: 45
  Confidence: 0.93

[25.0s - 55.2s]
  Text: ...Python programming. Let's start with the basics...
  Words: 52
  Confidence: 0.91
```

### `extract_frame_chunks()`

Extract frames from video at configured intervals.

```python
async def extract_frame_chunks(
    self,
    video_path: Path,
    video_id: str,
    duration_seconds: float,
    output_dir: Path,
) -> list[FrameChunk]:
    """Extract frames from video at configured intervals.

    Args:
        video_path: Path to video file.
        video_id: Parent video ID.
        duration_seconds: Total video duration.
        output_dir: Directory to save extracted frames.

    Returns:
        List of frame chunks with paths to extracted images.
    """
```

#### Example

```python
from pathlib import Path

frames = await service.extract_frame_chunks(
    video_path=Path("/tmp/video.mp4"),
    video_id="550e8400-e29b-41d4-a716-446655440000",
    duration_seconds=300.0,  # 5 minute video
    output_dir=Path("/tmp/frames"),
)

# With interval_seconds=5, this creates ~60 frames
print(f"Extracted {len(frames)} frames")

for frame in frames[:3]:
    print(f"Frame {frame.frame_number}:")
    print(f"  Timestamp: {frame.start_time:.1f}s")
    print(f"  Path: {frame.blob_path}")
    print(f"  Size: {frame.width}x{frame.height}")
```

### `create_audio_chunks()`

Create audio chunks for audio embedding (placeholder implementation).

```python
async def create_audio_chunks(
    self,
    audio_path: Path,
    video_id: str,
    duration_seconds: float,
    output_dir: Path,
) -> list[AudioChunk]:
    """Create audio chunks from audio file.

    Args:
        audio_path: Path to audio file.
        video_id: Parent video ID.
        duration_seconds: Total audio duration.
        output_dir: Directory to save audio chunks.

    Returns:
        List of audio chunks.
    """
```

### `create_video_chunks()`

Create video segment chunks for multimodal LLM analysis.

```python
async def create_video_chunks(
    self,
    video_path: Path,
    video_id: str,
    duration_seconds: float,
    output_dir: Path,
) -> list[VideoChunk]:
    """Create video segment chunks for multimodal LLM analysis.

    Args:
        video_path: Path to video file.
        video_id: Parent video ID.
        duration_seconds: Total video duration.
        output_dir: Directory to save video chunks.

    Returns:
        List of video chunks.
    """
```

Video chunks are constrained by size limits for LLM compatibility:

```python
# Only include chunks within size limit (e.g., 20MB for GPT-4o)
if chunk.is_within_size_limit(max_size_mb):
    chunks.append(chunk)
```

### `chunk_all()`

Convenience method to create all chunk types for a video.

```python
async def chunk_all(
    self,
    video_path: Path,
    audio_path: Path,
    video_id: str,
    duration_seconds: float,
    transcription_segments: list[TranscriptionSegment],
    language: str,
    output_dir: Path,
    *,
    include_frames: bool = True,
    include_audio: bool = False,
    include_video: bool = False,
) -> ChunkingResult:
    """Create all chunk types for a video.

    Args:
        video_path: Path to video file.
        audio_path: Path to audio file.
        video_id: Parent video ID.
        duration_seconds: Total video duration.
        transcription_segments: Transcription segments.
        language: Detected language.
        output_dir: Base output directory.
        include_frames: Whether to extract frames.
        include_audio: Whether to create audio chunks.
        include_video: Whether to create video chunks.

    Returns:
        ChunkingResult with all created chunks.
    """
```

#### Example

```python
result = await service.chunk_all(
    video_path=Path("/tmp/video.mp4"),
    audio_path=Path("/tmp/audio.mp3"),
    video_id="550e8400-e29b-41d4-a716-446655440000",
    duration_seconds=300.0,
    transcription_segments=segments,
    language="en",
    output_dir=Path("/tmp/chunks"),
    include_frames=True,
    include_audio=False,
    include_video=False,
)

print(f"Transcript chunks: {len(result.transcript_chunks)}")
print(f"Frame chunks: {len(result.frame_chunks)}")
print(f"Audio chunks: {len(result.audio_chunks)}")
print(f"Video chunks: {len(result.video_chunks)}")
```

## Configuration

Chunking behavior is controlled by `ChunkingSettings`:

```python
class ChunkingSettings(BaseModel):
    transcript: TranscriptChunkingSettings
    frame: FrameChunkingSettings
    audio: AudioChunkingSettings
    video: VideoChunkingSettings
```

### Transcript Settings

```json
{
  "transcript": {
    "chunk_seconds": 30,
    "overlap_seconds": 5,
    "min_chunk_words": 10
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `chunk_seconds` | 30 | Target duration per chunk |
| `overlap_seconds` | 5 | Overlap between consecutive chunks |
| `min_chunk_words` | 10 | Minimum words to create a chunk |

### Frame Settings

```json
{
  "frame": {
    "interval_seconds": 5,
    "max_frames": 500,
    "jpeg_quality": 85
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `interval_seconds` | 5 | Time between frame extractions |
| `max_frames` | 500 | Maximum frames per video |
| `jpeg_quality` | 85 | JPEG compression quality |

### Video Settings

```json
{
  "video": {
    "chunk_seconds": 30,
    "overlap_seconds": 5,
    "max_size_mb": 20
  }
}
```

| Setting | Default | Description |
|---------|---------|-------------|
| `chunk_seconds` | 30 | Duration per video chunk |
| `overlap_seconds` | 5 | Overlap between chunks |
| `max_size_mb` | 20 | Maximum chunk size (LLM limit) |

## Chunk Types

### TranscriptChunk

```python
@dataclass
class TranscriptChunk:
    id: str
    video_id: str
    modality: Modality = Modality.TRANSCRIPT
    text: str
    language: str
    confidence: float
    start_time: float
    end_time: float
    word_timestamps: list[WordTimestamp]
```

### FrameChunk

```python
@dataclass
class FrameChunk:
    id: str
    video_id: str
    modality: Modality = Modality.FRAME
    frame_number: int
    start_time: float
    end_time: float
    blob_path: str
    thumbnail_path: str
    width: int
    height: int
    description: str | None = None
```

### AudioChunk

```python
@dataclass
class AudioChunk:
    id: str
    video_id: str
    modality: Modality = Modality.AUDIO
    start_time: float
    end_time: float
    blob_path: str
    format: str  # "mp3", "wav"
```

### VideoChunk

```python
@dataclass
class VideoChunk:
    id: str
    video_id: str
    modality: Modality = Modality.VIDEO
    start_time: float
    end_time: float
    blob_path: str
    thumbnail_path: str
    width: int
    height: int
    fps: float
    has_audio: bool
    size_bytes: int
```

## Best Practices

### Overlap for Context

Use overlap to ensure semantic context is preserved:

```python
# Good: 5-10 second overlap for 30 second chunks
settings = ChunkingSettings(
    transcript=TranscriptChunkingSettings(
        chunk_seconds=30,
        overlap_seconds=5,
    )
)

# Bad: No overlap loses context at boundaries
settings = ChunkingSettings(
    transcript=TranscriptChunkingSettings(
        chunk_seconds=30,
        overlap_seconds=0,  # Don't do this
    )
)
```

### Frame Interval Selection

Choose frame intervals based on content type:

| Content Type | Recommended Interval |
|--------------|---------------------|
| Fast-paced action | 2-3 seconds |
| Presentations/lectures | 10-15 seconds |
| General content | 5 seconds |
| Static content | 15-30 seconds |
