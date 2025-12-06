"""Abstract base class for YouTube downloading services."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class YouTubeMetadata:
    """Metadata from a YouTube video."""

    id: str
    title: str
    description: str
    duration_seconds: int
    channel_name: str
    channel_id: str
    upload_date: datetime
    thumbnail_url: str
    view_count: int
    like_count: int | None
    tags: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)


@dataclass
class SubtitleTrack:
    """A subtitle/caption track."""

    language: str
    language_name: str
    content: str
    is_auto_generated: bool


@dataclass
class DownloadResult:
    """Result from downloading a YouTube video."""

    video_path: Path
    audio_path: Path
    metadata: YouTubeMetadata
    format_info: dict[str, Any]


class YouTubeDownloaderBase(ABC):
    """Abstract base class for YouTube downloading services.

    Implementations should handle:
    - yt-dlp (recommended)
    - pytube (simpler alternative)
    """

    @abstractmethod
    async def download(
        self,
        url: str,
        output_dir: Path,
        video_format: str = "mp4",
        audio_format: str = "mp3",
        max_resolution: int = 1080,
    ) -> DownloadResult:
        """Download video and extract audio.

        Args:
            url: YouTube video URL.
            output_dir: Directory to save files.
            video_format: Output video format.
            audio_format: Output audio format.
            max_resolution: Maximum video resolution (height in pixels).

        Returns:
            Download result with paths and metadata.

        Raises:
            VideoNotFoundException: If video doesn't exist.
            DownloadException: If download fails.
        """

    @abstractmethod
    async def download_audio_only(
        self,
        url: str,
        output_dir: Path,
        audio_format: str = "mp3",
        audio_quality: str = "192",
    ) -> tuple[Path, YouTubeMetadata]:
        """Download only the audio track.

        Args:
            url: YouTube video URL.
            output_dir: Directory to save file.
            audio_format: Output audio format.
            audio_quality: Audio bitrate in kbps.

        Returns:
            Tuple of (audio_path, metadata).
        """

    @abstractmethod
    async def get_metadata(self, url: str) -> YouTubeMetadata:
        """Get video metadata without downloading.

        Args:
            url: YouTube video URL.

        Returns:
            Video metadata.

        Raises:
            VideoNotFoundException: If video doesn't exist.
        """

    @abstractmethod
    async def get_subtitles(
        self,
        url: str,
        languages: list[str] | None = None,
        include_auto_generated: bool = True,
    ) -> list[SubtitleTrack]:
        """Get available subtitles/captions.

        Args:
            url: YouTube video URL.
            languages: Filter to specific languages (e.g., ['en', 'es']).
                      None returns all available.
            include_auto_generated: Whether to include auto-generated captions.

        Returns:
            List of available subtitle tracks.
        """

    @abstractmethod
    async def get_available_formats(self, url: str) -> list[dict[str, Any]]:
        """Get available video/audio formats.

        Args:
            url: YouTube video URL.

        Returns:
            List of format dictionaries with resolution, bitrate, etc.
        """

    @abstractmethod
    def validate_url(self, url: str) -> bool:
        """Validate if URL is a valid YouTube video URL.

        Args:
            url: URL to validate.

        Returns:
            True if valid YouTube URL.
        """

    @abstractmethod
    def extract_video_id(self, url: str) -> str | None:
        """Extract video ID from URL.

        Args:
            url: YouTube URL (various formats supported).

        Returns:
            Video ID string or None if invalid.
        """

    @property
    @abstractmethod
    def supported_url_patterns(self) -> list[str]:
        """URL patterns supported by this downloader.

        Returns:
            List of regex patterns for supported URLs.
        """
