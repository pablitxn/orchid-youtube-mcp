"""Unit tests for domain exceptions."""

from src.domain.exceptions import (
    ChunkNotFoundException,
    DomainException,
    EmbeddingException,
    IngestionException,
    InvalidYouTubeUrlException,
    QueryException,
    VideoNotFoundException,
    VideoNotReadyException,
)
from src.domain.models.video import VideoStatus


class TestDomainException:
    """Tests for base DomainException."""

    def test_is_exception(self):
        exc = DomainException("Test error")
        assert isinstance(exc, Exception)

    def test_message(self):
        exc = DomainException("Custom message")
        assert str(exc) == "Custom message"


class TestVideoNotFoundException:
    """Tests for VideoNotFoundException."""

    def test_attributes(self):
        exc = VideoNotFoundException("video-123")
        assert exc.video_id == "video-123"
        assert "video-123" in str(exc)
        assert isinstance(exc, DomainException)


class TestVideoNotReadyException:
    """Tests for VideoNotReadyException."""

    def test_attributes(self):
        exc = VideoNotReadyException("video-456", VideoStatus.DOWNLOADING)
        assert exc.video_id == "video-456"
        assert exc.status == VideoStatus.DOWNLOADING
        assert "video-456" in str(exc)
        assert "DOWNLOADING" in str(exc) or "downloading" in str(exc)


class TestChunkNotFoundException:
    """Tests for ChunkNotFoundException."""

    def test_attributes(self):
        exc = ChunkNotFoundException("chunk-789")
        assert exc.chunk_id == "chunk-789"
        assert "chunk-789" in str(exc)


class TestInvalidYouTubeUrlException:
    """Tests for InvalidYouTubeUrlException."""

    def test_attributes(self):
        exc = InvalidYouTubeUrlException("bad-url", "Missing video ID")
        assert exc.url == "bad-url"
        assert exc.reason == "Missing video ID"
        assert "bad-url" in str(exc)
        assert "Missing video ID" in str(exc)

    def test_default_reason(self):
        exc = InvalidYouTubeUrlException("bad-url")
        assert exc.reason == "Invalid URL"


class TestIngestionException:
    """Tests for IngestionException."""

    def test_attributes(self):
        exc = IngestionException("video-111", "download", "Connection timeout")
        assert exc.video_id == "video-111"
        assert exc.stage == "download"
        assert exc.reason == "Connection timeout"
        assert "video-111" in str(exc)
        assert "download" in str(exc)
        assert "Connection timeout" in str(exc)


class TestEmbeddingException:
    """Tests for EmbeddingException."""

    def test_attributes(self):
        exc = EmbeddingException("chunk-222", "Model unavailable")
        assert exc.chunk_id == "chunk-222"
        assert exc.reason == "Model unavailable"
        assert "chunk-222" in str(exc)


class TestQueryException:
    """Tests for QueryException."""

    def test_attributes(self):
        exc = QueryException("video-333", "No embeddings found")
        assert exc.video_id == "video-333"
        assert exc.reason == "No embeddings found"
        assert "video-333" in str(exc)
