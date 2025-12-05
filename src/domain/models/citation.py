"""Citation domain models for source references."""

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator

from src.domain.models.chunk import Modality


class TimestampRange(BaseModel):
    """A time range within a video.

    Represents a temporal segment that can be cited or referenced.
    """

    start_time: float = Field(ge=0, description="Start time in seconds")
    end_time: float = Field(ge=0, description="End time in seconds")

    @model_validator(mode="after")
    def validate_range(self) -> "TimestampRange":
        """Ensure end_time is greater than start_time."""
        if self.end_time < self.start_time:
            msg = (
                f"end_time ({self.end_time}) must be >= start_time ({self.start_time})"
            )
            raise ValueError(msg)
        return self

    @property
    def duration_seconds(self) -> float:
        """Calculate duration of the range."""
        return self.end_time - self.start_time

    def format_display(self) -> str:
        """Format as MM:SS - MM:SS for display."""

        def fmt(seconds: float) -> str:
            minutes = int(seconds // 60)
            secs = int(seconds % 60)
            return f"{minutes:02d}:{secs:02d}"

        return f"{fmt(self.start_time)} - {fmt(self.end_time)}"

    def format_display_long(self) -> str:
        """Format as HH:MM:SS - HH:MM:SS for longer videos."""

        def fmt(seconds: float) -> str:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            secs = int(seconds % 60)
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"

        return f"{fmt(self.start_time)} - {fmt(self.end_time)}"

    def to_youtube_url_param(self) -> str:
        """Generate YouTube timestamp parameter (seconds only)."""
        return f"t={int(self.start_time)}"

    def contains(self, timestamp: float) -> bool:
        """Check if a timestamp falls within this range.

        Args:
            timestamp: Time in seconds to check.

        Returns:
            True if timestamp is within range.
        """
        return self.start_time <= timestamp <= self.end_time

    def overlaps(self, other: "TimestampRange") -> bool:
        """Check if this range overlaps with another.

        Args:
            other: Another TimestampRange to compare.

        Returns:
            True if ranges overlap.
        """
        return not (
            self.end_time <= other.start_time or self.start_time >= other.end_time
        )

    def merge(self, other: "TimestampRange") -> "TimestampRange":
        """Merge two overlapping ranges into one.

        Args:
            other: Another TimestampRange to merge with.

        Returns:
            A new TimestampRange covering both ranges.
        """
        return TimestampRange(
            start_time=min(self.start_time, other.start_time),
            end_time=max(self.end_time, other.end_time),
        )

    @classmethod
    def from_seconds(cls, start: int | float, end: int | float) -> "TimestampRange":
        """Create from numeric seconds.

        Args:
            start: Start time in seconds.
            end: End time in seconds.

        Returns:
            A new TimestampRange.
        """
        return cls(start_time=float(start), end_time=float(end))


class SourceCitation(BaseModel):
    """A citation pointing to source material in a video.

    Citations are generated during query responses to provide
    verifiable references to the original content.
    """

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique citation identifier",
    )
    video_id: str = Field(description="Reference to source video")
    chunk_ids: list[str] = Field(
        min_length=1,
        description="Chunks that support this citation",
    )
    modality: Modality = Field(description="Primary modality of cited content")
    timestamp_range: TimestampRange = Field(description="Temporal location in video")
    relevance_score: float = Field(
        ge=0.0,
        le=1.0,
        description="How relevant this citation is to the query",
    )
    content_preview: str = Field(
        max_length=500,
        description="Short preview of cited content",
    )
    source_urls: dict[str, str] = Field(
        default_factory=dict,
        description="Presigned URLs for accessing sources by modality",
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this citation was created",
    )

    def youtube_url_with_timestamp(self, base_url: str) -> str:
        """Generate YouTube URL that jumps to this citation.

        Args:
            base_url: The base YouTube video URL.

        Returns:
            YouTube URL with timestamp parameter.
        """
        param = self.timestamp_range.to_youtube_url_param()
        separator = "&" if "?" in base_url else "?"
        return f"{base_url}{separator}{param}"

    def format_for_display(self) -> str:
        """Format citation for display in responses.

        Returns:
            Human-readable citation string.
        """
        time_str = self.timestamp_range.format_display()
        return f"[{time_str}] {self.content_preview}"

    @property
    def is_transcript_citation(self) -> bool:
        """Check if this is a transcript-based citation."""
        return self.modality == Modality.TRANSCRIPT

    @property
    def is_visual_citation(self) -> bool:
        """Check if this is a visual (frame/video) citation."""
        return self.modality in {Modality.FRAME, Modality.VIDEO}


class CitationGroup(BaseModel):
    """A group of related citations for a query response.

    Groups citations by relevance and provides aggregated access.
    """

    citations: list[SourceCitation] = Field(
        default_factory=list,
        description="List of citations in this group",
    )
    query: str = Field(description="The query these citations respond to")
    video_id: str = Field(description="Video these citations reference")

    @property
    def total_citations(self) -> int:
        """Get total number of citations."""
        return len(self.citations)

    @property
    def citations_by_modality(self) -> dict[Modality, list[SourceCitation]]:
        """Group citations by modality."""
        result: dict[Modality, list[SourceCitation]] = {}
        for citation in self.citations:
            if citation.modality not in result:
                result[citation.modality] = []
            result[citation.modality].append(citation)
        return result

    @property
    def top_citation(self) -> SourceCitation | None:
        """Get the most relevant citation."""
        if not self.citations:
            return None
        return max(self.citations, key=lambda c: c.relevance_score)

    def get_citations_above_threshold(
        self,
        threshold: float = 0.5,
    ) -> list[SourceCitation]:
        """Get citations above a relevance threshold.

        Args:
            threshold: Minimum relevance score (0-1).

        Returns:
            List of citations meeting the threshold.
        """
        return [c for c in self.citations if c.relevance_score >= threshold]

    def sorted_by_relevance(self, *, descending: bool = True) -> list[SourceCitation]:
        """Get citations sorted by relevance score.

        Args:
            descending: If True, highest relevance first.

        Returns:
            Sorted list of citations.
        """
        return sorted(
            self.citations,
            key=lambda c: c.relevance_score,
            reverse=descending,
        )

    def sorted_by_time(self) -> list[SourceCitation]:
        """Get citations sorted by timestamp.

        Returns:
            Citations sorted by start time.
        """
        return sorted(
            self.citations,
            key=lambda c: c.timestamp_range.start_time,
        )
