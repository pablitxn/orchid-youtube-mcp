"""Unit tests for VideoIngestionService."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.dtos.ingestion import IngestionStatus, IngestVideoRequest
from src.application.services.ingestion import IngestionError, VideoIngestionService
from src.commons.settings.models import Settings
from src.domain.models.video import VideoStatus


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
def mock_downloader():
    """Create mock YouTube downloader."""
    downloader = MagicMock()
    downloader.validate_url.return_value = True
    downloader.extract_video_id.return_value = "test123"

    download_result = MagicMock()
    download_result.video_path = Path("/tmp/video.mp4")
    download_result.audio_path = Path("/tmp/audio.mp3")

    metadata = MagicMock()
    metadata.id = "test123"
    metadata.title = "Test Video"
    metadata.description = "A test video"
    metadata.duration_seconds = 120
    metadata.channel_name = "Test Channel"
    metadata.channel_id = "UC123"
    metadata.upload_date = datetime(2024, 1, 1, tzinfo=UTC)
    metadata.thumbnail_url = "https://example.com/thumb.jpg"
    download_result.metadata = metadata

    async def mock_download(*args, **kwargs):
        return download_result

    downloader.download = mock_download
    return downloader


@pytest.fixture
def mock_transcriber():
    """Create mock transcription service."""
    transcriber = AsyncMock()

    transcription = MagicMock()
    transcription.language = "en"

    segment = MagicMock()
    segment.start_time = 0.0
    segment.end_time = 10.0
    segment.text = "This is a test transcript."
    segment.confidence = 0.95
    segment.words = []

    transcription.segments = [segment]
    transcriber.transcribe.return_value = transcription
    return transcriber


@pytest.fixture
def mock_embedder():
    """Create mock embedding service."""
    embedder = AsyncMock()
    embedder.text_dimensions = 1536
    embedder.max_batch_size = 100

    embedding = MagicMock()
    embedding.vector = [0.1] * 1536
    embedder.embed_texts.return_value = [embedding]
    return embedder


@pytest.fixture
def mock_frame_extractor():
    """Create mock frame extractor."""
    extractor = AsyncMock()

    frame = MagicMock()
    frame.timestamp = 2.0
    frame.frame_number = 1
    frame.width = 1920
    frame.height = 1080
    frame.path = Path("/tmp/frame.jpg")

    extractor.extract_frames.return_value = [frame]
    return extractor


@pytest.fixture
def mock_blob_storage():
    """Create mock blob storage."""
    blob = AsyncMock()
    blob.bucket_exists.return_value = True

    metadata = MagicMock()
    metadata.path = "test/path.mp4"
    blob.upload.return_value = metadata
    return blob


@pytest.fixture
def mock_vector_db():
    """Create mock vector database."""
    vector_db = AsyncMock()
    vector_db.collection_exists.return_value = True
    return vector_db


@pytest.fixture
def mock_document_db():
    """Create mock document database."""
    document_db = AsyncMock()
    document_db.find_one.return_value = None  # No existing video
    document_db.find_by_id.return_value = None
    document_db.find.return_value = []
    document_db.delete.return_value = True
    return document_db


@pytest.fixture
def ingestion_service(
    mock_downloader,
    mock_transcriber,
    mock_embedder,
    mock_frame_extractor,
    mock_blob_storage,
    mock_vector_db,
    mock_document_db,
    mock_settings,
):
    """Create ingestion service with mocked dependencies."""
    return VideoIngestionService(
        youtube_downloader=mock_downloader,
        transcription_service=mock_transcriber,
        text_embedding_service=mock_embedder,
        frame_extractor=mock_frame_extractor,
        blob_storage=mock_blob_storage,
        vector_db=mock_vector_db,
        document_db=mock_document_db,
        settings=mock_settings,
    )


class TestVideoIngestionService:
    """Tests for VideoIngestionService."""

    async def test_ingest_invalid_url(self, ingestion_service, mock_downloader):
        """Test ingestion with invalid URL."""
        mock_downloader.validate_url.return_value = False

        request = IngestVideoRequest(url="invalid-url")

        with pytest.raises(IngestionError, match="Invalid YouTube URL"):
            await ingestion_service.ingest(request)

    async def test_ingest_no_video_id(self, ingestion_service, mock_downloader):
        """Test ingestion when video ID cannot be extracted."""
        mock_downloader.extract_video_id.return_value = None

        request = IngestVideoRequest(url="https://youtube.com/watch?v=")

        with pytest.raises(IngestionError, match="Could not extract video ID"):
            await ingestion_service.ingest(request)

    async def test_ingest_existing_video_returns_existing(
        self, ingestion_service, mock_document_db
    ):
        """Test that ingesting existing video returns existing record."""
        existing = {
            "id": "existing-id",
            "youtube_id": "test123",
            "title": "Existing Video",
            "duration_seconds": 100,
            "status": VideoStatus.READY.value,
            "transcript_chunk_count": 5,
            "frame_chunk_count": 10,
            "created_at": datetime.now(UTC),
        }
        mock_document_db.find_one.return_value = existing

        request = IngestVideoRequest(url="https://youtube.com/watch?v=test123")

        result = await ingestion_service.ingest(request)

        assert result.youtube_id == "test123"
        assert result.status == IngestionStatus.COMPLETED

    async def test_get_ingestion_status_not_found(
        self, ingestion_service, mock_document_db
    ):
        """Test get_ingestion_status when video not found."""
        mock_document_db.find_by_id.return_value = None

        result = await ingestion_service.get_ingestion_status("nonexistent")
        assert result is None

    async def test_get_ingestion_status_found(
        self, ingestion_service, mock_document_db
    ):
        """Test get_ingestion_status when video exists."""
        mock_document_db.find_by_id.return_value = {
            "id": "video-1",
            "youtube_id": "test123",
            "title": "Test Video",
            "duration_seconds": 120,
            "status": VideoStatus.READY.value,
            "created_at": datetime.now(UTC),
        }

        result = await ingestion_service.get_ingestion_status("video-1")

        assert result is not None
        assert result.video_id == "video-1"
        assert result.status == IngestionStatus.COMPLETED

    async def test_list_videos_empty(self, ingestion_service, mock_document_db):
        """Test list_videos with no videos."""
        mock_document_db.find.return_value = []

        result = await ingestion_service.list_videos()
        assert result == []

    async def test_list_videos_with_results(self, ingestion_service, mock_document_db):
        """Test list_videos with results."""
        mock_document_db.find.return_value = [
            {
                "id": "video-1",
                "youtube_id": "test123",
                "title": "Video 1",
                "duration_seconds": 100,
                "status": VideoStatus.READY.value,
                "created_at": datetime.now(UTC),
            },
            {
                "id": "video-2",
                "youtube_id": "test456",
                "title": "Video 2",
                "duration_seconds": 200,
                "status": VideoStatus.READY.value,
                "created_at": datetime.now(UTC),
            },
        ]

        result = await ingestion_service.list_videos()

        assert len(result) == 2
        assert result[0].youtube_id == "test123"
        assert result[1].youtube_id == "test456"

    async def test_list_videos_with_status_filter(
        self, ingestion_service, mock_document_db
    ):
        """Test list_videos with status filter."""
        await ingestion_service.list_videos(status=VideoStatus.READY)

        mock_document_db.find.assert_called_once()
        call_args = mock_document_db.find.call_args
        assert call_args[0][1] == {"status": "ready"}

    async def test_delete_video_not_found(self, ingestion_service, mock_document_db):
        """Test delete_video when video not found."""
        mock_document_db.find_by_id.return_value = None

        result = await ingestion_service.delete_video("nonexistent")
        assert result is False

    async def test_delete_video_success(
        self,
        ingestion_service,
        mock_document_db,
        mock_vector_db,
        mock_blob_storage,
    ):
        """Test successful video deletion."""
        mock_document_db.find_by_id.return_value = {
            "id": "video-1",
            "youtube_id": "test123",
        }
        mock_blob_storage.list_blobs.return_value = []

        result = await ingestion_service.delete_video("video-1")

        assert result is True
        mock_vector_db.delete_by_filter.assert_called_once()
        mock_document_db.delete_many.assert_called()
        mock_document_db.delete.assert_called_once()


class TestTranscriptChunking:
    """Tests for transcript chunking logic."""

    def test_create_transcript_chunks_empty(self, ingestion_service):
        """Test chunking with empty segments."""
        chunks = ingestion_service._create_transcript_chunks([], "video-1", "en")
        assert chunks == []

    def test_create_transcript_chunks_single_segment(self, ingestion_service):
        """Test chunking with single segment."""
        segment = MagicMock()
        segment.start_time = 0.0
        segment.end_time = 10.0
        segment.text = "Hello world"
        segment.confidence = 0.95
        segment.words = []

        chunks = ingestion_service._create_transcript_chunks([segment], "video-1", "en")

        assert len(chunks) == 1
        assert chunks[0].text == "Hello world"
        assert chunks[0].video_id == "video-1"
        assert chunks[0].language == "en"

    def test_create_transcript_chunks_multiple_segments(self, ingestion_service):
        """Test chunking with multiple segments spanning chunk boundary."""
        segments = []
        for i in range(10):
            seg = MagicMock()
            seg.start_time = float(i * 5)
            seg.end_time = float((i + 1) * 5)
            seg.text = f"Segment {i}"
            seg.confidence = 0.9
            seg.words = []
            segments.append(seg)

        chunks = ingestion_service._create_transcript_chunks(segments, "video-1", "en")

        assert len(chunks) >= 1
        # Verify chunks have proper timestamps
        for chunk in chunks:
            assert chunk.start_time >= 0
            assert chunk.end_time > chunk.start_time
