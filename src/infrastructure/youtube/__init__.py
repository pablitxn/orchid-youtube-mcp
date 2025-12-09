"""YouTube downloading services."""

from src.infrastructure.youtube.base import (
    DownloadResult,
    SubtitleTrack,
    YouTubeDownloaderBase,
    YouTubeMetadata,
)
from src.infrastructure.youtube.downloader import (
    DownloadError,
    VideoNotFoundError,
    YtDlpDownloader,
)

__all__ = [
    # Base classes
    "YouTubeDownloaderBase",
    "YouTubeMetadata",
    "SubtitleTrack",
    "DownloadResult",
    # Implementations
    "YtDlpDownloader",
    # Exceptions
    "DownloadError",
    "VideoNotFoundError",
]
