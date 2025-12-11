"""Unit tests for YouTube downloader."""

import pytest

from src.infrastructure.youtube.downloader import YtDlpDownloader


@pytest.fixture
def downloader():
    """Create a downloader instance."""
    return YtDlpDownloader()


class TestUrlValidation:
    """Tests for URL validation."""

    def test_valid_watch_url(self, downloader):
        """Test standard watch URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert downloader.validate_url(url) is True

    def test_valid_short_url(self, downloader):
        """Test youtu.be short URL."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert downloader.validate_url(url) is True

    def test_valid_shorts_url(self, downloader):
        """Test YouTube Shorts URL."""
        url = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        assert downloader.validate_url(url) is True

    def test_valid_embed_url(self, downloader):
        """Test embed URL."""
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        assert downloader.validate_url(url) is True

    def test_invalid_url(self, downloader):
        """Test invalid URL."""
        url = "https://vimeo.com/12345"
        assert downloader.validate_url(url) is False

    def test_invalid_random_string(self, downloader):
        """Test random string."""
        assert downloader.validate_url("not a url") is False

    def test_valid_without_www(self, downloader):
        """Test URL without www."""
        url = "https://youtube.com/watch?v=dQw4w9WgXcQ"
        assert downloader.validate_url(url) is True

    def test_http_url(self, downloader):
        """Test HTTP URL (not HTTPS)."""
        url = "http://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert downloader.validate_url(url) is True


class TestVideoIdExtraction:
    """Tests for video ID extraction."""

    def test_extract_from_watch_url(self, downloader):
        """Test extraction from standard watch URL."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        assert downloader.extract_video_id(url) == "dQw4w9WgXcQ"

    def test_extract_from_short_url(self, downloader):
        """Test extraction from youtu.be URL."""
        url = "https://youtu.be/dQw4w9WgXcQ"
        assert downloader.extract_video_id(url) == "dQw4w9WgXcQ"

    def test_extract_from_shorts(self, downloader):
        """Test extraction from Shorts URL."""
        url = "https://www.youtube.com/shorts/dQw4w9WgXcQ"
        assert downloader.extract_video_id(url) == "dQw4w9WgXcQ"

    def test_extract_from_embed(self, downloader):
        """Test extraction from embed URL."""
        url = "https://www.youtube.com/embed/dQw4w9WgXcQ"
        assert downloader.extract_video_id(url) == "dQw4w9WgXcQ"

    def test_extract_with_extra_params(self, downloader):
        """Test extraction with additional URL parameters."""
        url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PLtest"
        assert downloader.extract_video_id(url) == "dQw4w9WgXcQ"

    def test_extract_from_invalid_url(self, downloader):
        """Test extraction from invalid URL returns None."""
        url = "https://vimeo.com/12345"
        assert downloader.extract_video_id(url) is None

    def test_extract_with_hyphen_in_id(self, downloader):
        """Test extraction with hyphen in video ID."""
        url = "https://www.youtube.com/watch?v=abc-def_123"
        assert downloader.extract_video_id(url) == "abc-def_123"


class TestSupportedPatterns:
    """Tests for supported URL patterns."""

    def test_patterns_list(self, downloader):
        """Test that supported patterns list is returned."""
        patterns = downloader.supported_url_patterns
        assert isinstance(patterns, list)
        assert len(patterns) > 0

    def test_patterns_are_valid_regex(self, downloader):
        """Test that all patterns are valid regex."""
        import re

        patterns = downloader.supported_url_patterns
        for pattern in patterns:
            # Should not raise
            re.compile(pattern)


class TestDownloaderInit:
    """Tests for downloader initialization."""

    def test_default_init(self):
        """Test default initialization."""
        downloader = YtDlpDownloader()
        assert downloader._cookies_file is None
        assert downloader._proxy is None
        assert downloader._rate_limit is None

    def test_init_with_options(self):
        """Test initialization with options."""
        from pathlib import Path

        downloader = YtDlpDownloader(
            cookies_file=Path("/tmp/cookies.txt"),
            proxy="http://proxy:8080",
            rate_limit="1M",
        )
        assert downloader._cookies_file == Path("/tmp/cookies.txt")
        assert downloader._proxy == "http://proxy:8080"
        assert downloader._rate_limit == "1M"
