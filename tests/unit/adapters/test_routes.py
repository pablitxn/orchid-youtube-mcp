"""Unit tests for API routes."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from src.adapters.main import create_app
from src.application.dtos.agent import AgentChatResult, AgentToolTrace
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
from src.application.dtos.youtube_auth import (
    YouTubeAuthMode,
    YouTubeAuthStatus,
)
from src.domain.models.chunk import TranscriptChunk
from src.domain.models.video import VideoMetadata, VideoStatus


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
    settings.document_db.collections.transcript_chunks = "transcript_chunks"
    settings.document_db.collections.frame_chunks = "frame_chunks"
    settings.document_db.collections.audio_chunks = "audio_chunks"
    settings.document_db.collections.video_chunks = "video_chunks"
    settings.document_db.collections.app_state = "app_state"
    settings.document_db.provider = "mongodb"
    settings.vector_db.collections.transcripts = "transcripts"
    settings.vector_db.provider = "qdrant"
    settings.blob_storage.buckets.videos = "videos"
    settings.blob_storage.buckets.frames = "frames"
    settings.blob_storage.buckets.chunks = "chunks"
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
    service.count_videos.return_value = 0
    return service


@pytest.fixture
def mock_query_service():
    """Create mock query service."""
    service = AsyncMock()
    return service


@pytest.fixture
def mock_storage_service():
    """Create mock storage service."""
    service = MagicMock()
    service.list_videos = AsyncMock(return_value=[])
    service.get_video_metadata = AsyncMock(return_value=None)
    service.get_chunks_for_video = AsyncMock(return_value=[])
    service.get_presigned_url = AsyncMock(return_value="https://signed.example/object")
    service._videos_bucket = "videos"
    service._frames_bucket = "frames"
    service._chunks_bucket = "chunks"
    return service


@pytest.fixture
def mock_agent_playground_service():
    """Create mock agent playground service."""
    service = AsyncMock()
    return service


@pytest.fixture
def mock_youtube_auth_service():
    """Create mock YouTube auth service."""
    service = AsyncMock()
    service.get_status.return_value = YouTubeAuthStatus(
        mode=YouTubeAuthMode.NONE,
        encryption_configured=True,
        has_managed_cookie=False,
        source_label=None,
        updated_at=None,
        runtime_file_present=False,
        configured_cookies_file=None,
        configured_browser=None,
        cookie_line_count=0,
        domain_count=0,
        contains_youtube_domains=False,
        has_login_cookie_names=False,
    )
    return service


@pytest.fixture
def client(
    mock_settings,
    mock_factory,
    mock_ingestion_service,
    mock_query_service,
    mock_storage_service,
    mock_agent_playground_service,
    mock_youtube_auth_service,
):
    """Create test client with mocked dependencies."""
    from src.adapters.dependencies import (
        get_agent_playground_service,
        get_infrastructure_factory,
        get_ingestion_service,
        get_query_service,
        get_settings,
        get_storage_service,
        get_youtube_auth_service,
    )

    with (
        patch("src.adapters.main.get_settings", return_value=mock_settings),
        patch("src.adapters.dependencies.init_services", new_callable=AsyncMock),
        patch("src.adapters.dependencies.shutdown_services", new_callable=AsyncMock),
    ):
        app = create_app()
        # Override dependencies using FastAPI's proper mechanism
        app.dependency_overrides[get_settings] = lambda: mock_settings
        app.dependency_overrides[get_infrastructure_factory] = lambda: mock_factory
        app.dependency_overrides[get_ingestion_service] = lambda: mock_ingestion_service
        app.dependency_overrides[get_query_service] = lambda: mock_query_service
        app.dependency_overrides[get_storage_service] = lambda: mock_storage_service
        app.dependency_overrides[get_agent_playground_service] = (
            lambda: mock_agent_playground_service
        )
        app.dependency_overrides[get_youtube_auth_service] = (
            lambda: mock_youtube_auth_service
        )
        yield TestClient(app, raise_server_exceptions=False)


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


class TestAdminRoutes:
    """Tests for admin inspection endpoints."""

    def test_get_admin_overview(self, client, mock_factory, mock_storage_service):
        """Test dashboard overview aggregation."""
        mock_document_db = MagicMock()

        async def count_side_effect(collection: str, filters: dict[str, str]) -> int:
            if collection == "videos":
                return {
                    "pending": 1,
                    "downloading": 1,
                    "transcribing": 0,
                    "extracting": 0,
                    "embedding": 0,
                    "ready": 3,
                    "failed": 1,
                }.get(filters.get("status", ""), 0)

            return {
                "transcript_chunks": 9,
                "frame_chunks": 107,
                "audio_chunks": 4,
                "video_chunks": 0,
            }.get(collection, 0)

        mock_document_db.count = AsyncMock(side_effect=count_side_effect)
        mock_factory.get_document_db.return_value = mock_document_db
        mock_storage_service.list_videos.return_value = [
            MagicMock(created_at=datetime.now(UTC))
        ]

        response = client.get("/v1/admin/overview")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["total_videos"] == 6
        assert data["videos_by_status"]["completed"] == 3
        assert data["total_chunks"] == 120

    def test_get_admin_video_detail(
        self,
        client,
        mock_storage_service,
    ):
        """Test admin detail route for a stored video."""
        mock_storage_service.get_video_metadata.return_value = VideoMetadata(
            id="video-1",
            youtube_id="abc123xyz89",
            youtube_url="https://www.youtube.com/watch?v=abc123xyz89",
            title="Test Video",
            description="Demo video",
            duration_seconds=125,
            channel_name="Channel",
            channel_id="channel-1",
            upload_date=datetime.now(UTC),
            thumbnail_url="https://img.youtube.com/demo.jpg",
            status=VideoStatus.READY,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            transcript_chunk_count=4,
            frame_chunk_count=12,
            audio_chunk_count=2,
            video_chunk_count=0,
            blob_path_video="video-1/video.mp4",
            blob_path_audio="video-1/audio.mp3",
        )

        response = client.get("/v1/admin/videos/video-1")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "completed"
        assert data["chunk_counts"]["frame"] == 12
        assert len(data["artifacts"]) == 3

    def test_get_admin_video_chunks(
        self,
        client,
        mock_storage_service,
    ):
        """Test chunk inspection route."""
        mock_storage_service.get_video_metadata.return_value = VideoMetadata(
            id="video-1",
            youtube_id="abc123xyz89",
            youtube_url="https://www.youtube.com/watch?v=abc123xyz89",
            title="Test Video",
            description="Demo video",
            duration_seconds=125,
            channel_name="Channel",
            channel_id="channel-1",
            upload_date=datetime.now(UTC),
            thumbnail_url="https://img.youtube.com/demo.jpg",
            status=VideoStatus.READY,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
            transcript_chunk_count=1,
            frame_chunk_count=0,
            audio_chunk_count=0,
            video_chunk_count=0,
        )
        mock_storage_service.get_chunks_for_video.return_value = [
            TranscriptChunk(
                id="chunk-1",
                video_id="video-1",
                start_time=0,
                end_time=30,
                text="Transcript text here",
                language="en",
                confidence=0.98,
                blob_path="video-1/transcript/chunk-1.json",
            )
        ]

        response = client.get(
            "/v1/admin/videos/video-1/chunks",
            params={"modality": "transcript"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["pagination"]["total_items"] == 1
        assert data["chunks"][0]["id"] == "chunk-1"

    def test_get_youtube_auth_status(self, client, mock_youtube_auth_service):
        """Test fetching managed YouTube auth status."""
        mock_youtube_auth_service.get_status.return_value = YouTubeAuthStatus(
            mode=YouTubeAuthMode.MANAGED_COOKIE,
            encryption_configured=True,
            has_managed_cookie=True,
            source_label="utility account",
            updated_at=datetime.now(UTC),
            runtime_file_present=True,
            configured_cookies_file=None,
            configured_browser=None,
            cookie_line_count=24,
            domain_count=2,
            contains_youtube_domains=True,
            has_login_cookie_names=True,
        )

        response = client.get("/v1/admin/youtube-auth")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["mode"] == "managed_cookie"
        assert data["cookie_line_count"] == 24

    def test_save_youtube_cookie(self, client, mock_youtube_auth_service):
        """Test saving managed YouTube cookie content."""
        mock_youtube_auth_service.save_cookie.return_value = YouTubeAuthStatus(
            mode=YouTubeAuthMode.MANAGED_COOKIE,
            encryption_configured=True,
            has_managed_cookie=True,
            source_label="utility account",
            updated_at=datetime.now(UTC),
            runtime_file_present=True,
            configured_cookies_file=None,
            configured_browser=None,
            cookie_line_count=24,
            domain_count=2,
            contains_youtube_domains=True,
            has_login_cookie_names=True,
        )

        response = client.put(
            "/v1/admin/youtube-auth/cookie",
            json={
                "cookie_text": (
                    "# Netscape HTTP Cookie File\n"
                    ".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tsecret\n"
                ),
                "source_label": "utility account",
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["has_managed_cookie"] is True
        assert data["source_label"] == "utility account"

    def test_clear_youtube_cookie(self, client, mock_youtube_auth_service):
        """Test clearing the managed YouTube cookie."""
        mock_youtube_auth_service.clear_cookie.return_value = YouTubeAuthStatus(
            mode=YouTubeAuthMode.NONE,
            encryption_configured=True,
            has_managed_cookie=False,
            source_label=None,
            updated_at=None,
            runtime_file_present=False,
            configured_cookies_file=None,
            configured_browser=None,
            cookie_line_count=0,
            domain_count=0,
            contains_youtube_domains=False,
            has_login_cookie_names=False,
        )

        response = client.delete("/v1/admin/youtube-auth/cookie")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["mode"] == "none"


class TestAgentRoutes:
    """Tests for the agent playground route."""

    def test_chat_with_video_agent_success(self, client, mock_agent_playground_service):
        """Test successful selected-video agent chat."""
        mock_agent_playground_service.chat.return_value = AgentChatResult(
            reply="The chorus starts around 00:42.",
            response_id="resp_123",
            tool_traces=[
                AgentToolTrace(
                    tool_name="query_selected_video",
                    mcp_tool_name="query_video",
                    arguments={"query": "When does the chorus start?"},
                    result_preview='{"answer":"The chorus starts around 00:42."}',
                )
            ],
        )

        response = client.post(
            "/v1/agent/videos/video-1/chat",
            json={
                "messages": [
                    {"role": "user", "content": "When does the chorus start?"}
                ]
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["reply"] == "The chorus starts around 00:42."
        assert data["tool_traces"][0]["mcp_tool_name"] == "query_video"

    def test_chat_with_video_agent_not_found(
        self,
        client,
        mock_agent_playground_service,
    ):
        """Test agent chat for a non-existent video."""
        mock_agent_playground_service.chat.side_effect = ValueError(
            "Video not found: missing"
        )

        response = client.post(
            "/v1/agent/videos/missing/chat",
            json={"messages": [{"role": "user", "content": "hi"}]},
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
