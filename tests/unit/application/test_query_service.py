"""Unit tests for VideoQueryService."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.dtos.query import (
    GetSourcesRequest,
    QueryModality,
    QueryVideoRequest,
)
from src.application.services.query import VideoQueryService
from src.commons.settings.models import Settings


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    settings = MagicMock(spec=Settings)
    settings.vector_db.collections.transcripts = "transcripts"
    settings.document_db.collections.videos = "videos"
    settings.document_db.collections.transcript_chunks = "transcript_chunks"
    settings.document_db.collections.frame_chunks = "frame_chunks"
    settings.blob_storage.buckets.frames = "frames"
    return settings


@pytest.fixture
def mock_embedder():
    """Create mock embedding service."""
    embedder = AsyncMock()
    embedding = MagicMock()
    embedding.vector = [0.1] * 1536
    embedder.embed_texts.return_value = [embedding]
    return embedder


@pytest.fixture
def mock_llm():
    """Create mock LLM service."""
    llm = AsyncMock()
    response = MagicMock()
    response.content = "This is an answer based on the video content."
    llm.generate.return_value = response
    return llm


@pytest.fixture
def mock_vector_db():
    """Create mock vector database."""
    vector_db = AsyncMock()
    result = MagicMock()
    result.payload = {"chunk_id": "chunk-1", "video_id": "video-1"}
    result.score = 0.85
    vector_db.search.return_value = [result]
    return vector_db


@pytest.fixture
def mock_document_db():
    """Create mock document database."""
    document_db = AsyncMock()

    async def find_by_id_side_effect(collection, doc_id):
        if collection == "videos":
            return {
                "id": "video-1",
                "title": "Test Video",
                "status": "ready",
                "youtube_url": "https://youtube.com/watch?v=test123",
            }
        if collection == "transcript_chunks":
            return {
                "id": doc_id,
                "text": "This is some transcript text from the video.",
                "start_time": 10.0,
                "end_time": 40.0,
            }
        return None

    document_db.find_by_id.side_effect = find_by_id_side_effect
    document_db.find.return_value = []
    return document_db


@pytest.fixture
def mock_blob_storage():
    """Create mock blob storage."""
    blob = AsyncMock()
    blob.exists.return_value = True
    blob.generate_presigned_url.return_value = "https://storage.example.com/thumb.jpg"
    return blob


@pytest.fixture
def query_service(
    mock_embedder,
    mock_llm,
    mock_vector_db,
    mock_document_db,
    mock_blob_storage,
    mock_settings,
):
    """Create query service with mocked dependencies."""
    return VideoQueryService(
        text_embedding_service=mock_embedder,
        llm_service=mock_llm,
        vector_db=mock_vector_db,
        document_db=mock_document_db,
        settings=mock_settings,
        blob_storage=mock_blob_storage,
    )


class TestVideoQueryService:
    """Tests for VideoQueryService."""

    async def test_query_video_success(self, query_service, mock_embedder, mock_llm):
        """Test successful video query."""
        request = QueryVideoRequest(
            query="What is discussed in this video?",
            modalities=[QueryModality.TRANSCRIPT],
            max_citations=5,
        )

        result = await query_service.query("video-1", request)

        assert result.answer is not None
        assert result.confidence > 0
        assert result.query_metadata.video_id == "video-1"
        mock_embedder.embed_texts.assert_called_once()
        mock_llm.generate.assert_called_once()

    async def test_query_video_not_found(self, query_service, mock_document_db):
        """Test query when video not found."""
        mock_document_db.find_by_id.return_value = None

        request = QueryVideoRequest(query="Test query")

        with pytest.raises(ValueError, match="Video not found"):
            await query_service.query("nonexistent", request)

    async def test_query_video_not_ready(self, query_service, mock_document_db):
        """Test query when video not ready."""

        async def find_not_ready(collection, doc_id):
            if collection == "videos":
                return {"id": doc_id, "status": "processing"}
            return None

        mock_document_db.find_by_id.side_effect = find_not_ready

        request = QueryVideoRequest(query="Test query")

        with pytest.raises(ValueError, match="not ready"):
            await query_service.query("video-1", request)

    async def test_query_with_no_results(self, query_service, mock_vector_db, mock_llm):
        """Test query with no matching chunks."""
        mock_vector_db.search.return_value = []

        request = QueryVideoRequest(query="Unrelated question")

        result = await query_service.query("video-1", request)

        assert "couldn't find relevant information" in result.answer.lower()
        assert result.confidence == 0.0
        mock_llm.generate.assert_not_called()

    async def test_citations_include_youtube_url(self, query_service):
        """Test that citations include YouTube URL with timestamp."""
        request = QueryVideoRequest(
            query="What is discussed?",
            max_citations=5,
        )

        result = await query_service.query("video-1", request)

        assert len(result.citations) > 0
        citation = result.citations[0]
        assert citation.youtube_url is not None
        assert "t=10" in citation.youtube_url

    async def test_format_timestamp_minutes(self, query_service):
        """Test timestamp formatting for minutes."""
        result = query_service._format_timestamp(125.5)
        assert result == "02:05"

    async def test_format_timestamp_hours(self, query_service):
        """Test timestamp formatting for hours."""
        result = query_service._format_timestamp(3725.0)
        assert result == "01:02:05"


class TestGetSources:
    """Tests for get_sources method."""

    async def test_get_sources_success(self, query_service, mock_document_db):
        """Test successful source retrieval."""
        mock_document_db.find_by_id.side_effect = None
        mock_document_db.find_by_id.return_value = {
            "id": "chunk-1",
            "text": "Sample transcript text",
            "start_time": 10.0,
            "end_time": 40.0,
        }

        async def find_by_id_impl(collection, doc_id):
            if collection == "videos":
                return {"id": "video-1", "title": "Test"}
            return {
                "id": doc_id,
                "text": "Sample text",
                "start_time": 10.0,
                "end_time": 40.0,
            }

        mock_document_db.find_by_id.side_effect = find_by_id_impl

        request = GetSourcesRequest(
            citation_ids=["chunk-1"],
            include_artifacts=["transcript_text"],
        )

        result = await query_service.get_sources("video-1", request)

        assert len(result.sources) == 1
        assert "transcript_text" in result.sources[0].artifacts
        assert result.expires_at > datetime.now(UTC)

    async def test_get_sources_video_not_found(self, query_service, mock_document_db):
        """Test get_sources when video not found."""
        mock_document_db.find_by_id.return_value = None

        request = GetSourcesRequest(citation_ids=["chunk-1"])

        with pytest.raises(ValueError, match="not found"):
            await query_service.get_sources("nonexistent", request)


class TestGetThumbnailUrl:
    """Tests for _get_thumbnail_url method."""

    async def test_get_thumbnail_url_success(
        self, query_service, mock_document_db, mock_blob_storage
    ):
        """Test successful thumbnail URL generation."""
        mock_document_db.find.return_value = [
            {"thumbnail_path": "video-1/frames/thumb_00001.jpg", "start_time": 10.0}
        ]

        url = await query_service._get_thumbnail_url("video-1", 12.0, 3600)

        assert url == "https://storage.example.com/thumb.jpg"
        mock_blob_storage.exists.assert_called_once()
        mock_blob_storage.generate_presigned_url.assert_called_once()

    async def test_get_thumbnail_url_no_blob_storage(self, mock_settings):
        """Test thumbnail URL when blob storage not configured."""
        service = VideoQueryService(
            text_embedding_service=AsyncMock(),
            llm_service=AsyncMock(),
            vector_db=AsyncMock(),
            document_db=AsyncMock(),
            settings=mock_settings,
            blob_storage=None,
        )

        url = await service._get_thumbnail_url("video-1", 10.0, 3600)
        assert url is None

    async def test_get_thumbnail_url_no_frames(self, query_service, mock_document_db):
        """Test thumbnail URL when no frames found."""
        mock_document_db.find.return_value = []

        url = await query_service._get_thumbnail_url("video-1", 10.0, 3600)
        assert url is None

    async def test_get_thumbnail_url_blob_not_exists(
        self, query_service, mock_document_db, mock_blob_storage
    ):
        """Test thumbnail URL when blob doesn't exist."""
        mock_document_db.find.return_value = [
            {"thumbnail_path": "video-1/frames/thumb.jpg", "start_time": 10.0}
        ]
        mock_blob_storage.exists.return_value = False

        url = await query_service._get_thumbnail_url("video-1", 10.0, 3600)
        assert url is None
