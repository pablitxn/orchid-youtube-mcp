"""DTOs for managed YouTube authentication state."""

from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


class YouTubeAuthMode(str, Enum):
    """How yt-dlp authentication is currently resolved."""

    MANAGED_COOKIE = "managed_cookie"
    STATIC_FILE = "static_file"
    BROWSER = "browser"
    NONE = "none"


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
    configured_cookies_file: str | None = Field(
        default=None,
        description="Static cookies file configured in settings",
    )
    configured_browser: str | None = Field(
        default=None,
        description="Browser extraction fallback configured in settings",
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
