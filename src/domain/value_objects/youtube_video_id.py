"""YouTube Video ID value object."""

from __future__ import annotations

import re
from typing import Annotated

from pydantic import BaseModel, Field, field_validator

from src.domain.exceptions import InvalidYouTubeUrlException

# Pattern for valid YouTube video IDs: 11 characters, alphanumeric + _ and -
YOUTUBE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{11}$")

# Patterns to extract video ID from various YouTube URL formats
URL_PATTERNS = [
    re.compile(r"(?:v=|/v/)([a-zA-Z0-9_-]{11})"),  # Standard watch URLs
    re.compile(r"(?:youtu\.be/)([a-zA-Z0-9_-]{11})"),  # Short URLs
    re.compile(r"(?:embed/)([a-zA-Z0-9_-]{11})"),  # Embed URLs
    re.compile(r"(?:shorts/)([a-zA-Z0-9_-]{11})"),  # Shorts URLs
]


class YouTubeVideoId(BaseModel):
    """Value object representing a validated YouTube video ID.

    Ensures the ID follows YouTube's format (11 characters, alphanumeric + _-).

    Examples:
        >>> vid = YouTubeVideoId(value="dQw4w9WgXcQ")
        >>> vid.to_url()
        'https://www.youtube.com/watch?v=dQw4w9WgXcQ'

        >>> vid = YouTubeVideoId.from_url("https://youtu.be/dQw4w9WgXcQ")
        >>> vid.value
        'dQw4w9WgXcQ'
    """

    value: Annotated[
        str,
        Field(
            min_length=11,
            max_length=11,
            description="YouTube video ID (11 characters)",
        ),
    ]

    @field_validator("value")
    @classmethod
    def validate_format(cls, v: str) -> str:
        """Validate that the value matches YouTube ID format."""
        if not YOUTUBE_ID_PATTERN.match(v):
            msg = (
                f"Invalid YouTube video ID format: '{v}'. "
                "Must be 11 characters: alphanumeric, underscore, or hyphen."
            )
            raise ValueError(msg)
        return v

    @classmethod
    def from_url(cls, url: str) -> YouTubeVideoId:
        """Extract video ID from various YouTube URL formats.

        Supported formats:
            - https://www.youtube.com/watch?v=VIDEO_ID
            - https://youtube.com/watch?v=VIDEO_ID
            - https://youtu.be/VIDEO_ID
            - https://www.youtube.com/embed/VIDEO_ID
            - https://www.youtube.com/v/VIDEO_ID
            - https://www.youtube.com/shorts/VIDEO_ID

        Args:
            url: A YouTube URL in any supported format.

        Returns:
            A YouTubeVideoId instance.

        Raises:
            InvalidYouTubeUrlException: If the URL is invalid or ID cannot be extracted.
        """
        if not url or not isinstance(url, str):
            raise InvalidYouTubeUrlException(str(url), "URL cannot be empty")

        url = url.strip()

        for pattern in URL_PATTERNS:
            match = pattern.search(url)
            if match:
                video_id = match.group(1)
                return cls(value=video_id)

        # Check if the input is just a video ID
        if YOUTUBE_ID_PATTERN.match(url):
            return cls(value=url)

        raise InvalidYouTubeUrlException(url, "Could not extract video ID")

    def to_url(self, *, short: bool = False) -> str:
        """Convert to a YouTube URL.

        Args:
            short: If True, return short youtu.be URL.

        Returns:
            YouTube URL string.
        """
        if short:
            return f"https://youtu.be/{self.value}"
        return f"https://www.youtube.com/watch?v={self.value}"

    def to_embed_url(self) -> str:
        """Convert to YouTube embed URL."""
        return f"https://www.youtube.com/embed/{self.value}"

    def to_thumbnail_url(self, quality: str = "hqdefault") -> str:
        """Get thumbnail URL for this video.

        Args:
            quality: Thumbnail quality. Options:
                - default (120x90)
                - mqdefault (320x180)
                - hqdefault (480x360)
                - sddefault (640x480)
                - maxresdefault (1280x720)

        Returns:
            Thumbnail URL.
        """
        return f"https://img.youtube.com/vi/{self.value}/{quality}.jpg"

    def __str__(self) -> str:
        return self.value

    def __hash__(self) -> int:
        return hash(self.value)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, YouTubeVideoId):
            return self.value == other.value
        if isinstance(other, str):
            return self.value == other
        return False
