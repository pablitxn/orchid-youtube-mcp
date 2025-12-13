"""Unit tests for API routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.application.dtos.ingestion import IngestionStatus, IngestVideoResponse
from src.application.dtos.query import (
    CitationDTO,
    QueryMetadata,
    QueryModality,
    QueryVideoResponse,
    SourceArtifact,
    SourceDetail,
    SourcesResponse,
    TimestampRangeDTO,
)


@pytest.fixture
def mock_settings():
    """Create mock settings for the app."""
    settings = MagicMock()
    settings.app.name = "test-app"
    settings.app.version = "0.1.0"
    settings.app.environment = "test"
    settings.server.cors_origins = ["*"]
    settings.server.api_prefix = "/v1"
    settings.server.docs_enabled = True
    # Add collections settings for health checks
    settings.document_db.collections.videos = "videos"
    settings.document_db.provider = "mongodb"
    settings.vector_db.collections.transcripts = "transcripts"
    settings.vector_db.provider = "qdrant"
    settings.blob_storage.buckets.videos = "videos"
    settings.blob_storage.provider = "minio"
    return settings


@pytest.fixture
def mock_factory():
    """Create mock infrastructure factory."""
    factory = MagicMock()
    factory.get_blob_storage.return_value = MagicMock()
    factory.get_vector_db.return_value = MagicMock()
    factory.get_document_db.return_value = MagicMock()
    factory.get_youtube_downloader.return_value = MagicMock()
    factory.get_transcription_service.return_value = MagicMock()
    factory.get_text_embedding_service.return_value = MagicMock()
    factory.get_frame_extractor.return_value = MagicMock()
    factory.get_llm_service.return_value = MagicMock()
    return factory


@pytest.fixture
def mock_ingestion_service():
    """Create mock ingestion service."""
    service = AsyncMock()
    return service


@pytest.fixture
def mock_query_service():
    """Create mock query service."""
    service = AsyncMock()
    return service


@pytest.fixture
def client(mock_settings, mock_factory, mock_ingestion_service, mock_query_service):
    """Create test client with mocked dependencies."""
    from src.api.dependencies import (
        get_infrastructure_factory,
        get_ingestion_service,
        get_query_service,
        get_settings,
    )

    with (
        patch("src.api.main.get_settings", return_value=mock_settings),
        patch("src.api.dependencies.init_services", new_callable=AsyncMock),
        patch("src.api.dependencies.shutdown_services", new_callable=AsyncMock),
    ):
        app = create_app()
        # Override dependencies using FastAPI's proper mechanism
        app.dependency_overrides[get_settings] = lambda: mock_settings
        app.dependency_overrides[get_infrastructure_factory] = lambda: mock_factory
        app.dependency_overrides[get_ingestion_service] = lambda: mock_ingestion_service
        app.dependency_overrides[get_query_service] = lambda: mock_query_service
        yield TestClient(app, raise_server_exceptions=False)


class TestHealthRoutes:
    """Tests for health check endpoints."""

    def test_health_check(self, client):
        """Test basic health check."""
        response = client.get("/health")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "healthy"

    def test_liveness_check(self, client):
        """Test liveness probe."""
        response = client.get("/health/live")
        assert response.status_code == status.HTTP_200_OK

    def test_readiness_check(self, client):
        """Test readiness probe."""
        response = client.get("/health/ready")
        # May return 200 or 503 depending on service state
        assert response.status_code in [
            status.HTTP_200_OK,
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ]


class TestIngestionRoutes:
    """Tests for ingestion endpoints."""

    def test_ingest_video_success(self, client, mock_ingestion_service):
        """Test successful video ingestion."""
        mock_ingestion_service.ingest.return_value = IngestVideoResponse(
            video_id="uuid-1234",
            youtube_id="test123",
            title="Test Video",
            duration_seconds=120,
            status=IngestionStatus.COMPLETED,
            chunk_counts={"transcript": 5, "frame": 20},
            created_at=datetime.now(UTC),
        )

        response = client.post(
            "/v1/videos/ingest",
            json={"youtube_url": "https://youtube.com/watch?v=test123"},
        )

        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["video_id"] == "uuid-1234"
        assert data["youtube_id"] == "test123"

    def test_ingest_video_invalid_url(self, client, mock_ingestion_service):
        """Test ingestion with invalid URL."""
        from src.application.dtos.ingestion import ProcessingStep
        from src.application.services.ingestion import IngestionError

        mock_ingestion_service.ingest.side_effect = IngestionError(
            "Invalid YouTube URL", ProcessingStep.VALIDATING
        )

        response = client.post(
            "/v1/videos/ingest",
            json={"youtube_url": "invalid-url"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST

    def test_get_ingestion_status_found(self, client, mock_ingestion_service):
        """Test getting ingestion status for existing video."""
        mock_ingestion_service.get_ingestion_status.return_value = IngestVideoResponse(
            video_id="uuid-1234",
            youtube_id="test123",
            title="Test Video",
            duration_seconds=120,
            status=IngestionStatus.COMPLETED,
            chunk_counts={},
            created_at=datetime.now(UTC),
        )

        response = client.get("/v1/videos/uuid-1234/status")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["video_id"] == "uuid-1234"

    def test_get_ingestion_status_not_found(self, client, mock_ingestion_service):
        """Test getting ingestion status for non-existent video."""
        mock_ingestion_service.get_ingestion_status.return_value = None

        response = client.get("/v1/videos/nonexistent/status")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestQueryRoutes:
    """Tests for query endpoints."""

    def test_query_video_success(self, client, mock_query_service):
        """Test successful video query."""
        mock_query_service.query.return_value = QueryVideoResponse(
            answer="This video discusses machine learning.",
            reasoning="Based on transcript analysis.",
            confidence=0.85,
            citations=[
                CitationDTO(
                    id="chunk-1",
                    modality=QueryModality.TRANSCRIPT,
                    timestamp_range=TimestampRangeDTO(
                        start_time=10.0,
                        end_time=40.0,
                        display="00:10 - 00:40",
                    ),
                    content_preview="In this video...",
                    relevance_score=0.9,
                )
            ],
            query_metadata=QueryMetadata(
                video_id="video-1",
                video_title="Test Video",
                modalities_searched=[QueryModality.TRANSCRIPT],
                chunks_analyzed=5,
                processing_time_ms=150,
            ),
        )

        response = client.post(
            "/v1/videos/video-1/query",
            json={"query": "What is this video about?"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "answer" in data
        assert data["confidence"] == 0.85

    def test_query_video_not_found(self, client, mock_query_service):
        """Test query for non-existent video."""
        mock_query_service.query.side_effect = ValueError("Video not found: video-1")

        response = client.post(
            "/v1/videos/video-1/query",
            json={"query": "What is this about?"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_query_video_not_ready(self, client, mock_query_service):
        """Test query for video that's not ready."""
        mock_query_service.query.side_effect = ValueError(
            "Video not ready for querying"
        )

        response = client.post(
            "/v1/videos/video-1/query",
            json={"query": "What is this about?"},
        )

        assert response.status_code == status.HTTP_409_CONFLICT


class TestSourcesRoutes:
    """Tests for sources endpoints."""

    def test_get_sources_success(self, client, mock_query_service):
        """Test successful sources retrieval."""
        mock_query_service.get_sources.return_value = SourcesResponse(
            sources=[
                SourceDetail(
                    citation_id="chunk-1",
                    modality=QueryModality.TRANSCRIPT,
                    timestamp_range=TimestampRangeDTO(
                        start_time=10.0,
                        end_time=40.0,
                        display="00:10 - 00:40",
                    ),
                    artifacts={
                        "transcript_text": SourceArtifact(
                            type="transcript_text",
                            content="Sample text...",
                        )
                    },
                )
            ],
            expires_at=datetime.now(UTC),
        )

        response = client.get(
            "/v1/videos/video-1/sources",
            params={"citation_ids": ["chunk-1"]},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["sources"]) == 1

    def test_get_sources_video_not_found(self, client, mock_query_service):
        """Test sources for non-existent video."""
        mock_query_service.get_sources.side_effect = ValueError(
            "Video not found: video-1"
        )

        response = client.get(
            "/v1/videos/video-1/sources",
            params={"citation_ids": ["chunk-1"]},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestVideoManagementRoutes:
    """Tests for video management endpoints."""

    def test_list_videos_empty(self, client, mock_ingestion_service):
        """Test listing videos when none exist."""
        mock_ingestion_service.list_videos.return_value = []

        response = client.get("/v1/videos")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["videos"] == []

    def test_list_videos_with_results(self, client, mock_ingestion_service):
        """Test listing videos with results."""
        mock_ingestion_service.list_videos.return_value = [
            IngestVideoResponse(
                video_id="uuid-1",
                youtube_id="test1",
                title="Video 1",
                duration_seconds=100,
                status=IngestionStatus.COMPLETED,
                chunk_counts={},
                created_at=datetime.now(UTC),
            ),
            IngestVideoResponse(
                video_id="uuid-2",
                youtube_id="test2",
                title="Video 2",
                duration_seconds=200,
                status=IngestionStatus.COMPLETED,
                chunk_counts={},
                created_at=datetime.now(UTC),
            ),
        ]

        response = client.get("/v1/videos")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data["videos"]) == 2

    def test_get_video_by_id(self, client, mock_ingestion_service):
        """Test getting single video by ID."""
        mock_ingestion_service.get_ingestion_status.return_value = IngestVideoResponse(
            video_id="uuid-1",
            youtube_id="test1",
            title="Video 1",
            duration_seconds=100,
            status=IngestionStatus.COMPLETED,
            chunk_counts={},
            created_at=datetime.now(UTC),
        )

        response = client.get("/v1/videos/uuid-1")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["id"] == "uuid-1"  # Route returns 'id' not 'video_id'

    def test_delete_video_success(self, client, mock_ingestion_service):
        """Test successful video deletion."""
        # Mock get_ingestion_status to return a video (needed for existence check)
        mock_ingestion_service.get_ingestion_status.return_value = IngestVideoResponse(
            video_id="uuid-1",
            youtube_id="test1",
            title="Video 1",
            duration_seconds=100,
            status=IngestionStatus.COMPLETED,
            chunk_counts={},
            created_at=datetime.now(UTC),
        )
        mock_ingestion_service.delete_video.return_value = True

        response = client.delete(
            "/v1/videos/uuid-1",
            headers={"X-Confirm-Delete": "true"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["success"] is True

    def test_delete_video_not_found(self, client, mock_ingestion_service):
        """Test deleting non-existent video."""
        mock_ingestion_service.get_ingestion_status.return_value = None

        response = client.delete(
            "/v1/videos/nonexistent",
            headers={"X-Confirm-Delete": "true"},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
