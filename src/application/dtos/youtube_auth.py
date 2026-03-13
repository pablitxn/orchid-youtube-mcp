"""DTOs for managed YouTube authentication state."""

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class YouTubeAuthMode(str, Enum):
    """How yt-dlp authentication is currently resolved."""

    MANAGED_COOKIE = "managed_cookie"
    NONE = "none"


class AudioDownloadPreset(str, Enum):
    """Supported browser-download presets for audio-only fetches."""

    MP3_128 = "mp3_128"
    MP3_192 = "mp3_192"
    M4A_128 = "m4a_128"
    OPUS_160 = "opus_160"


class YouTubeAuthStatus(BaseModel):
    """Public status for YouTube authentication in the admin UI."""

    mode: YouTubeAuthMode = Field(description="Active authentication mode")
    encryption_configured: bool = Field(
        description="Whether the managed cookie encryption key is configured"
    )
    has_managed_cookie: bool = Field(
        description="Whether a managed cookie is stored in the app database"
    )
    source_label: str | None = Field(
        default=None,
        description="Optional operator label for the stored cookie",
    )
    updated_at: datetime | None = Field(
        default=None,
        description="When the managed cookie was last updated",
    )
    runtime_file_present: bool = Field(
        description="Whether the runtime cookies.txt file currently exists"
    )
    cookie_line_count: int = Field(
        ge=0,
        description="Number of parsed cookie lines in the managed cookie",
    )
    domain_count: int = Field(
        ge=0,
        description="Distinct cookie domains detected in the managed cookie",
    )
    contains_youtube_domains: bool = Field(
        description="Whether the cookie includes YouTube or Google domains",
    )
    has_login_cookie_names: bool = Field(
        description="Whether the cookie includes likely authenticated login cookies",
    )


class ManagedYouTubeCookie(BaseModel):
    """Stored managed cookies.txt payload."""

    id: str = Field(default="youtube_auth_cookie")
    source_label: str | None = Field(default=None)
    encrypted_cookie_text: str = Field(min_length=1)
    cookie_line_count: int = Field(ge=0)
    domain_count: int = Field(ge=0)
    contains_youtube_domains: bool = Field(default=False)
    has_login_cookie_names: bool = Field(default=False)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class PreparedYouTubeAudioDownload:
    """Ephemeral audio download prepared for direct browser delivery."""

    youtube_url: str
    youtube_id: str
    title: str
    channel_name: str
    duration_seconds: int
    auth_mode: YouTubeAuthMode
    audio_format: str
    audio_quality: str
    file_path: Path
    cleanup_dir: Path


class YouTubeDownloadTestResult(BaseModel):
    """Result of an ephemeral yt-dlp download diagnostic."""

    youtube_url: str = Field(description="Tested YouTube URL")
    youtube_id: str = Field(description="Resolved YouTube video ID")
    title: str = Field(description="Resolved video title")
    channel_name: str = Field(description="Resolved channel name")
    duration_seconds: int = Field(ge=0, description="Video duration in seconds")
    auth_mode: YouTubeAuthMode = Field(
        description="Authentication mode that was active during the download"
    )
    downloaded_bytes: int = Field(
        ge=0,
        description="Size of the temporary downloaded artifact before deletion",
    )
    artifact_name: str = Field(description="Temporary artifact filename")
    elapsed_ms: int = Field(
        ge=0,
        description="End-to-end diagnostic time in milliseconds",
    )
    note: str = Field(
        description="Operator-facing note about what happened during the test"
    )
