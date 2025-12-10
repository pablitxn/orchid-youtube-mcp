# Value Objects

Immutable domain primitives that encapsulate validation logic.

## YouTubeVideoId

A validated YouTube video ID ensuring correct format.

```python
import re
from pydantic import BaseModel, Field


class YouTubeVideoId(BaseModel):
    """
    Value object representing a validated YouTube video ID.

    YouTube IDs are exactly 11 characters: alphanumeric plus _ and -.
    """

    value: str = Field(
        min_length=11,
        max_length=11,
        pattern=r"^[a-zA-Z0-9_-]{11}$"
    )

    @classmethod
    def from_url(cls, url: str) -> "YouTubeVideoId":
        """Extract video ID from various YouTube URL formats."""
        patterns = [
            r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",
            r"(?:embed/)([a-zA-Z0-9_-]{11})",
            r"(?:shorts/)([a-zA-Z0-9_-]{11})",
        ]

        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return cls(value=match.group(1))

        raise InvalidYouTubeUrlException(url, "Could not extract video ID")

    def to_url(self) -> str:
        """Convert to standard YouTube watch URL."""
        return f"https://www.youtube.com/watch?v={self.value}"

    def to_short_url(self) -> str:
        """Convert to shortened youtu.be URL."""
        return f"https://youtu.be/{self.value}"

    def to_embed_url(self) -> str:
        """Convert to embeddable URL."""
        return f"https://www.youtube.com/embed/{self.value}"

    def __str__(self) -> str:
        return self.value

    def __eq__(self, other: object) -> bool:
        if isinstance(other, YouTubeVideoId):
            return self.value == other.value
        if isinstance(other, str):
            return self.value == other
        return False

    def __hash__(self) -> int:
        return hash(self.value)
```

### Supported URL Formats

| Format | Example | Extracted ID |
|--------|---------|--------------|
| Standard | `https://www.youtube.com/watch?v=dQw4w9WgXcQ` | `dQw4w9WgXcQ` |
| Short | `https://youtu.be/dQw4w9WgXcQ` | `dQw4w9WgXcQ` |
| Embed | `https://www.youtube.com/embed/dQw4w9WgXcQ` | `dQw4w9WgXcQ` |
| Shorts | `https://www.youtube.com/shorts/dQw4w9WgXcQ` | `dQw4w9WgXcQ` |
| With params | `https://youtube.com/watch?v=dQw4w9WgXcQ&t=30` | `dQw4w9WgXcQ` |

### Examples

```python
# From URL
video_id = YouTubeVideoId.from_url("https://youtu.be/dQw4w9WgXcQ")
print(video_id.value)  # "dQw4w9WgXcQ"

# Direct creation
video_id = YouTubeVideoId(value="dQw4w9WgXcQ")

# Convert to URLs
print(video_id.to_url())        # "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
print(video_id.to_short_url())  # "https://youtu.be/dQw4w9WgXcQ"
print(video_id.to_embed_url())  # "https://www.youtube.com/embed/dQw4w9WgXcQ"

# Invalid ID raises validation error
try:
    YouTubeVideoId(value="invalid")
except ValidationError:
    print("Invalid video ID")
```

---

## ChunkingConfig

Configuration parameters for chunk generation.

```python
from pydantic import BaseModel, Field


class ChunkingConfig(BaseModel):
    """Configuration for chunk generation."""

    # Transcript chunking
    transcript_chunk_seconds: int = Field(
        default=30,
        ge=5,
        le=300,
        description="Duration of each transcript chunk in seconds"
    )
    transcript_overlap_seconds: int = Field(
        default=5,
        ge=0,
        le=30,
        description="Overlap between consecutive transcript chunks"
    )

    # Frame extraction
    frame_interval_seconds: float = Field(
        default=2.0,
        ge=0.5,
        le=60,
        description="Interval between extracted frames"
    )

    # Audio chunking
    audio_chunk_seconds: int = Field(
        default=60,
        ge=10,
        le=600,
        description="Duration of each audio chunk in seconds"
    )

    # Video chunking (for multimodal LLMs)
    video_chunk_seconds: int = Field(
        default=30,
        ge=5,
        le=120,
        description="Duration of each video chunk"
    )
    video_chunk_overlap_seconds: int = Field(
        default=2,
        ge=0,
        le=10,
        description="Overlap between consecutive video chunks"
    )
    video_chunk_max_size_mb: float = Field(
        default=20.0,
        ge=1.0,
        le=100.0,
        description="Maximum size per video chunk in MB"
    )

    def estimate_transcript_chunks(self, duration_seconds: int) -> int:
        """Estimate number of transcript chunks for a video."""
        if duration_seconds <= self.transcript_chunk_seconds:
            return 1
        effective_chunk = self.transcript_chunk_seconds - self.transcript_overlap_seconds
        return max(1, (duration_seconds - self.transcript_overlap_seconds) // effective_chunk)

    def estimate_frame_count(self, duration_seconds: int) -> int:
        """Estimate number of frames to extract."""
        return max(1, int(duration_seconds / self.frame_interval_seconds))
```

### Presets

```python
# Default configuration
default_config = ChunkingConfig()

# High-density for short videos
dense_config = ChunkingConfig(
    transcript_chunk_seconds=15,
    transcript_overlap_seconds=3,
    frame_interval_seconds=1.0,
    video_chunk_seconds=15
)

# Low-density for long videos
sparse_config = ChunkingConfig(
    transcript_chunk_seconds=60,
    transcript_overlap_seconds=10,
    frame_interval_seconds=5.0,
    video_chunk_seconds=60
)

# Audio-only (podcasts)
audio_config = ChunkingConfig(
    transcript_chunk_seconds=30,
    transcript_overlap_seconds=5,
    frame_interval_seconds=60,  # Minimal frames
    audio_chunk_seconds=60
)
```

### Example Usage

```python
config = ChunkingConfig(
    transcript_chunk_seconds=30,
    frame_interval_seconds=5.0
)

# Estimate chunks for a 10-minute video
duration = 600  # seconds
estimated_transcripts = config.estimate_transcript_chunks(duration)
estimated_frames = config.estimate_frame_count(duration)

print(f"Estimated transcript chunks: {estimated_transcripts}")  # ~24
print(f"Estimated frames: {estimated_frames}")  # 120
```

---

## TimestampRange

A time range within a video (also used in Citations).

```python
class TimestampRange(BaseModel):
    """A time range within a video."""

    start_time: float = Field(ge=0, description="Start time in seconds")
    end_time: float = Field(ge=0, description="End time in seconds")

    def duration_seconds(self) -> float:
        """Get duration of this range."""
        return self.end_time - self.start_time

    def format_display(self) -> str:
        """Format as MM:SS - MM:SS for display."""
        def fmt(s: float) -> str:
            minutes = int(s // 60)
            seconds = int(s % 60)
            return f"{minutes:02d}:{seconds:02d}"
        return f"{fmt(self.start_time)} - {fmt(self.end_time)}"

    def format_display_hours(self) -> str:
        """Format as HH:MM:SS - HH:MM:SS for longer videos."""
        def fmt(s: float) -> str:
            hours = int(s // 3600)
            minutes = int((s % 3600) // 60)
            seconds = int(s % 60)
            if hours > 0:
                return f"{hours}:{minutes:02d}:{seconds:02d}"
            return f"{minutes:02d}:{seconds:02d}"
        return f"{fmt(self.start_time)} - {fmt(self.end_time)}"

    def to_youtube_url_param(self) -> str:
        """Generate YouTube timestamp parameter."""
        return f"t={int(self.start_time)}"

    def contains(self, timestamp: float) -> bool:
        """Check if a timestamp is within this range."""
        return self.start_time <= timestamp < self.end_time

    def overlaps(self, other: "TimestampRange") -> bool:
        """Check if this range overlaps with another."""
        return not (self.end_time <= other.start_time or self.start_time >= other.end_time)

    def merge(self, other: "TimestampRange") -> "TimestampRange":
        """Merge with another range (must overlap)."""
        if not self.overlaps(other):
            raise ValueError("Cannot merge non-overlapping ranges")
        return TimestampRange(
            start_time=min(self.start_time, other.start_time),
            end_time=max(self.end_time, other.end_time)
        )
```

### Examples

```python
# Create a range
range1 = TimestampRange(start_time=30.0, end_time=60.0)

print(range1.duration_seconds())  # 30.0
print(range1.format_display())    # "00:30 - 01:00"
print(range1.to_youtube_url_param())  # "t=30"

# Check containment
print(range1.contains(45.0))  # True
print(range1.contains(90.0))  # False

# Merge overlapping ranges
range2 = TimestampRange(start_time=50.0, end_time=90.0)
merged = range1.merge(range2)
print(merged.format_display())  # "00:30 - 01:30"
```

---

## ProcessingOptions

Options for video processing.

```python
class ProcessingOptions(BaseModel):
    """Options for video processing."""

    extract_frames: bool = Field(
        default=True,
        description="Whether to extract video frames"
    )
    extract_audio_chunks: bool = Field(
        default=False,
        description="Whether to create audio chunks"
    )
    extract_video_chunks: bool = Field(
        default=False,
        description="Whether to create video chunks for multimodal LLMs"
    )
    language_hint: str | None = Field(
        default=None,
        description="Hint for transcription language (ISO 639-1)"
    )
    max_resolution: int = Field(
        default=1080,
        ge=144,
        le=2160,
        description="Maximum video resolution to download"
    )
    generate_descriptions: bool = Field(
        default=False,
        description="Generate AI descriptions for frames/video chunks"
    )
```

---

## Validation Benefits

Value objects provide several benefits:

### 1. Validation at Construction

```python
# Invalid values fail immediately
try:
    YouTubeVideoId(value="short")  # Too short
except ValidationError as e:
    print(e)  # String should have at least 11 characters
```

### 2. Type Safety

```python
def process_video(video_id: YouTubeVideoId) -> None:
    # Guaranteed to be valid
    url = video_id.to_url()
```

### 3. Encapsulated Logic

```python
# All URL generation logic in one place
video_id = YouTubeVideoId.from_url(any_youtube_url)
standard_url = video_id.to_url()
embed_url = video_id.to_embed_url()
```

### 4. Immutability

```python
# Value objects should be treated as immutable
# Create new instances instead of modifying
new_config = ChunkingConfig(
    **config.model_dump(),
    frame_interval_seconds=3.0
)
```

## Related

- [VideoMetadata](video-metadata.md) - Uses YouTubeVideoId
- [Chunks](chunks.md) - Configured via ChunkingConfig
- [Citations](citations.md) - Uses TimestampRange
