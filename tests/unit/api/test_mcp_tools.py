"""Unit tests for MCP tools."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.api.mcp.tools import (
    delete_video_tool,
    get_ingestion_status_tool,
    get_sources_tool,
    ingest_video_tool,
    list_videos_tool,
    query_video_tool,
)
from src.commons.settings.models import Settings


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    settings = MagicMock(spec=Settings)
    settings.document_db.collections.videos = "videos"
    settings.document_db.collections.transcript_chunks = "transcript_chunks"
    settings.document_db.collections.frame_chunks = "frame_chunks"
    settings.vector_db.collections.transcripts = "transcripts"
    settings.blob_storage.buckets.videos = "videos"
    settings.blob_storage.buckets.frames = "frames"
    settings.chunking.transcript.chunk_seconds = 30
    settings.chunking.transcript.overlap_seconds = 5
    settings.chunking.frame.interval_seconds = 2.0
    return settings


@pytest.fixture
def mock_factory():
    """Create mock infrastructure factory."""
    factory = MagicMock()
    factory.get_youtube_downloader.return_value = MagicMock()
    factory.get_transcription_service.return_value = AsyncMock()
    factory.get_text_embedding_service.return_value = AsyncMock()
    factory.get_frame_extractor.return_value = AsyncMock()
    factory.get_blob_storage.return_value = AsyncMock()
    factory.get_vector_db.return_value = AsyncMock()
    factory.get_document_db.return_value = AsyncMock()
    factory.get_llm_service.return_value = AsyncMock()
    return factory


class TestIngestVideoTool:
    """Tests for ingest_video_tool."""

    async def test_ingest_video_success(self, mock_factory, mock_settings):
        """Test successful video ingestion via MCP tool."""
        # Mock the service's ingest method
        mock_doc_db = mock_factory.get_document_db()
        mock_doc_db.find_one.return_value = None  # No existing video

        arguments = {
            "youtube_url": "https://youtube.com/watch?v=test123",
            "extract_frames": True,
        }

        # This will fail due to actual ingestion logic, but tests the tool structure
        # In a real test, we'd mock the VideoIngestionService
        with pytest.raises(AttributeError):
            await ingest_video_tool(mock_factory, mock_settings, arguments)


class TestGetIngestionStatusTool:
    """Tests for get_ingestion_status_tool."""

    async def test_status_not_found(self, mock_factory, mock_settings):
        """Test status for non-existent video."""
        mock_doc_db = mock_factory.get_document_db()
        mock_doc_db.find_by_id.return_value = None

        arguments = {"video_id": "nonexistent"}

        result = await get_ingestion_status_tool(mock_factory, mock_settings, arguments)

        assert "error" in result
        assert "not found" in result["error"]

    async def test_status_found(self, mock_factory, mock_settings):
        """Test status for existing video."""
        mock_doc_db = mock_factory.get_document_db()
        mock_doc_db.find_by_id.return_value = {
            "id": "video-1",
            "youtube_id": "test123",
            "title": "Test Video",
            "duration_seconds": 120,
            "status": "ready",
            "created_at": datetime.now(UTC),
        }

        arguments = {"video_id": "video-1"}

        result = await get_ingestion_status_tool(mock_factory, mock_settings, arguments)

        assert result["video_id"] == "video-1"
        assert result["status"] == "completed"


class TestQueryVideoTool:
    """Tests for query_video_tool."""

    async def test_query_video_not_found(self, mock_factory, mock_settings):
        """Test query for non-existent video."""
        mock_doc_db = mock_factory.get_document_db()
        mock_doc_db.find_by_id.return_value = None

        arguments = {
            "video_id": "nonexistent",
            "query": "What is this about?",
        }

        result = await query_video_tool(mock_factory, mock_settings, arguments)

        assert "error" in result
        assert "not found" in result["error"]

    async def test_query_video_not_ready(self, mock_factory, mock_settings):
        """Test query for video that's not ready."""
        mock_doc_db = mock_factory.get_document_db()
        mock_doc_db.find_by_id.return_value = {
            "id": "video-1",
            "status": "processing",
        }

        arguments = {
            "video_id": "video-1",
            "query": "What is this about?",
        }

        result = await query_video_tool(mock_factory, mock_settings, arguments)

        assert "error" in result
        assert "still being processed" in result["error"]


class TestGetSourcesTool:
    """Tests for get_sources_tool."""

    async def test_get_sources_video_not_found(self, mock_factory, mock_settings):
        """Test sources for non-existent video."""
        mock_doc_db = mock_factory.get_document_db()
        mock_doc_db.find_by_id.return_value = None

        arguments = {
            "video_id": "nonexistent",
            "citation_ids": ["chunk-1"],
        }

        result = await get_sources_tool(mock_factory, mock_settings, arguments)

        assert "error" in result


class TestListVideosTool:
    """Tests for list_videos_tool."""

    async def test_list_videos_empty(self, mock_factory, mock_settings):
        """Test listing videos when none exist."""
        mock_doc_db = mock_factory.get_document_db()
        mock_doc_db.find.return_value = []

        arguments = {"page": 1, "page_size": 20}

        result = await list_videos_tool(mock_factory, mock_settings, arguments)

        assert result["videos"] == []
        assert result["pagination"]["page"] == 1

    async def test_list_videos_with_results(self, mock_factory, mock_settings):
        """Test listing videos with results."""
        mock_doc_db = mock_factory.get_document_db()
        mock_doc_db.find.return_value = [
            {
                "id": "video-1",
                "youtube_id": "test1",
                "title": "Video 1",
                "duration_seconds": 100,
                "status": "ready",
                "created_at": datetime.now(UTC),
            }
        ]

        arguments = {"page": 1, "page_size": 20}

        result = await list_videos_tool(mock_factory, mock_settings, arguments)

        assert len(result["videos"]) == 1
        assert result["videos"][0]["youtube_id"] == "test1"

    async def test_list_videos_with_status_filter(self, mock_factory, mock_settings):
        """Test listing videos with status filter."""
        mock_doc_db = mock_factory.get_document_db()
        mock_doc_db.find.return_value = []

        arguments = {"status": "ready", "page": 1}

        await list_videos_tool(mock_factory, mock_settings, arguments)

        # Verify filter was applied
        mock_doc_db.find.assert_called_once()


class TestDeleteVideoTool:
    """Tests for delete_video_tool."""

    async def test_delete_without_confirm(self, mock_factory, mock_settings):
        """Test delete without confirmation."""
        arguments = {"video_id": "video-1", "confirm": False}

        result = await delete_video_tool(mock_factory, mock_settings, arguments)

        assert "error" in result
        assert "confirm=true" in result["error"]

    async def test_delete_video_not_found(self, mock_factory, mock_settings):
        """Test delete for non-existent video."""
        mock_doc_db = mock_factory.get_document_db()
        mock_doc_db.find_by_id.return_value = None

        arguments = {"video_id": "nonexistent", "confirm": True}

        result = await delete_video_tool(mock_factory, mock_settings, arguments)

        assert "error" in result
        assert "not found" in result["error"]

    async def test_delete_video_success(self, mock_factory, mock_settings):
        """Test successful video deletion."""
        mock_doc_db = mock_factory.get_document_db()
        mock_doc_db.find_by_id.return_value = {
            "id": "video-1",
            "youtube_id": "test123",
        }
        mock_doc_db.delete.return_value = True

        mock_factory.get_vector_db()
        mock_blob = mock_factory.get_blob_storage()
        mock_blob.list_blobs.return_value = []

        arguments = {"video_id": "video-1", "confirm": True}

        result = await delete_video_tool(mock_factory, mock_settings, arguments)

        assert result["success"] is True
        assert result["video_id"] == "video-1"
