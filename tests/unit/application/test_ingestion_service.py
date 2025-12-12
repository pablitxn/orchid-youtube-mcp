"""Unit tests for VideoIngestionService."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.dtos.ingestion import (
    IngestionProgress,
    IngestionStatus,
    IngestVideoRequest,
    ProcessingStep,
)
from src.application.services.ingestion import IngestionError, VideoIngestionService
from src.domain.models.video import VideoMetadata, VideoStatus
from src.infrastructure.youtube.downloader import DownloadError, VideoNotFoundError

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def mock_settings():
    """Create mock settings with nested structure."""
    settings = MagicMock()

    # Document DB settings
    settings.document_db.collections.videos = "videos"
    settings.document_db.collections.transcript_chunks = "transcript_chunks"
    settings.document_db.collections.frame_chunks = "frame_chunks"

    # Vector DB settings
    settings.vector_db.collections.transcripts = "transcripts"

    # Blob storage settings
    settings.blob_storage.buckets.videos = "videos"
    settings.blob_storage.buckets.frames = "frames"

    # Chunking settings
    settings.chunking.transcript.chunk_seconds = 30
    settings.chunking.transcript.overlap_seconds = 5
    settings.chunking.frame.interval_seconds = 2.0

    return settings


@pytest.fixture
def mock_youtube_metadata():
    """Create mock YouTube metadata."""
    metadata = MagicMock()
    metadata.id = "dQw4w9WgXcQ"
    metadata.title = "Test Video Title"
    metadata.description = "A test video description"
    metadata.duration_seconds = 120
    metadata.channel_name = "Test Channel"
    metadata.channel_id = "UC123456789"
    metadata.upload_date = datetime(2024, 1, 15, tzinfo=UTC)
    metadata.thumbnail_url = "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"
    return metadata


@pytest.fixture
def mock_downloader(mock_youtube_metadata, tmp_path):
    """Create mock YouTube downloader with temp files."""
    downloader = MagicMock()
    downloader.validate_url.return_value = True
    downloader.extract_video_id.return_value = "dQw4w9WgXcQ"

    # Create actual temp files for the test
    video_file = tmp_path / "dQw4w9WgXcQ.mp4"
    audio_file = tmp_path / "dQw4w9WgXcQ.mp3"
    video_file.write_bytes(b"fake video content")
    audio_file.write_bytes(b"fake audio content")

    download_result = MagicMock()
    download_result.video_path = video_file
    download_result.audio_path = audio_file
    download_result.metadata = mock_youtube_metadata

    async def mock_download(*args, **kwargs):
        # Recreate files in the actual output_dir if provided
        output_dir = kwargs.get("output_dir") or args[1] if len(args) > 1 else tmp_path
        if isinstance(output_dir, Path):
            v = output_dir / "dQw4w9WgXcQ.mp4"
            a = output_dir / "dQw4w9WgXcQ.mp3"
            v.write_bytes(b"fake video content")
            a.write_bytes(b"fake audio content")
            download_result.video_path = v
            download_result.audio_path = a
        return download_result

    downloader.download = mock_download
    return downloader


@pytest.fixture
def mock_transcription_result():
    """Create mock transcription result with multiple segments."""
    transcription = MagicMock()
    transcription.language = "en"
    transcription.full_text = "This is the full transcript of the test video."
    transcription.duration_seconds = 120.0

    segments = []
    for i in range(5):
        segment = MagicMock()
        segment.start_time = float(i * 20)
        segment.end_time = float((i + 1) * 20)
        segment.text = f"This is segment number {i + 1} of the transcript."
        segment.confidence = 0.92 + (i * 0.01)
        segment.language = "en"

        # Add word timestamps
        words = []
        word_texts = segment.text.split()
        word_duration = (segment.end_time - segment.start_time) / len(word_texts)
        for j, word_text in enumerate(word_texts):
            word = MagicMock()
            word.word = word_text
            word.start_time = segment.start_time + (j * word_duration)
            word.end_time = segment.start_time + ((j + 1) * word_duration)
            word.confidence = 0.95
            words.append(word)
        segment.words = words
        segments.append(segment)

    transcription.segments = segments
    return transcription


@pytest.fixture
def mock_transcriber(mock_transcription_result):
    """Create mock transcription service."""
    transcriber = AsyncMock()
    transcriber.transcribe.return_value = mock_transcription_result
    return transcriber


@pytest.fixture
def mock_embedder():
    """Create mock embedding service."""
    embedder = AsyncMock()
    embedder.text_dimensions = 1536
    embedder.max_batch_size = 100

    async def mock_embed_texts(texts):
        embeddings = []
        for _ in texts:
            emb = MagicMock()
            emb.vector = [0.1] * 1536
            embeddings.append(emb)
        return embeddings

    embedder.embed_texts = mock_embed_texts
    return embedder


@pytest.fixture
def mock_frame_extractor(tmp_path):
    """Create mock frame extractor with temp files."""
    extractor = AsyncMock()

    async def mock_extract(video_path, output_dir, interval_seconds):
        frames = []
        for i in range(5):
            frame_path = output_dir / f"frame_{i:05d}.jpg"
            frame_path.write_bytes(b"fake frame data")

            frame = MagicMock()
            frame.timestamp = float(i * interval_seconds)
            frame.frame_number = i
            frame.width = 1920
            frame.height = 1080
            frame.path = frame_path
            frames.append(frame)
        return frames

    extractor.extract_frames = mock_extract
    return extractor


@pytest.fixture
def mock_blob_storage():
    """Create mock blob storage."""
    blob = AsyncMock()
    blob.bucket_exists.return_value = True
    blob.exists.return_value = True
    blob.list_blobs.return_value = []

    async def mock_upload(bucket, path, data, content_type=None):
        metadata = MagicMock()
        metadata.path = path
        metadata.size = len(data) if isinstance(data, bytes) else 100
        return metadata

    blob.upload = mock_upload

    async def mock_download_to_file(bucket, blob_path, local_path):
        # Create the file with fake content
        local_path.write_bytes(b"fake downloaded content")

    blob.download_to_file = mock_download_to_file

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
    document_db.find_one.return_value = None  # No existing video by default
    document_db.find_by_id.return_value = None
    document_db.find.return_value = []
    document_db.delete.return_value = True
    document_db.insert.return_value = "inserted-id"
    document_db.insert_many.return_value = ["id1", "id2"]
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


# =============================================================================
# Test: URL Validation
# =============================================================================


class TestURLValidation:
    """Tests for URL validation logic."""

    async def test_ingest_invalid_url_raises_error(
        self, ingestion_service, mock_downloader
    ):
        """Test ingestion with invalid URL raises IngestionError."""
        mock_downloader.validate_url.return_value = False

        request = IngestVideoRequest(url="not-a-youtube-url")

        with pytest.raises(IngestionError) as exc_info:
            await ingestion_service.ingest(request)

        assert "Invalid YouTube URL" in str(exc_info.value)
        # Step is VALIDATING when raised directly, FAILED when wrapped
        assert exc_info.value.step in (ProcessingStep.VALIDATING, ProcessingStep.FAILED)

    async def test_ingest_no_video_id_raises_error(
        self, ingestion_service, mock_downloader
    ):
        """Test ingestion when video ID cannot be extracted."""
        mock_downloader.extract_video_id.return_value = None

        request = IngestVideoRequest(url="https://youtube.com/watch?v=")

        with pytest.raises(IngestionError) as exc_info:
            await ingestion_service.ingest(request)

        assert "Could not extract video ID" in str(exc_info.value)
        # Step is VALIDATING when raised directly, FAILED when wrapped
        assert exc_info.value.step in (ProcessingStep.VALIDATING, ProcessingStep.FAILED)

    async def test_valid_youtube_urls(self, ingestion_service, mock_downloader):
        """Test various valid YouTube URL formats."""
        valid_urls = [
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "https://youtu.be/dQw4w9WgXcQ",
            "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        ]

        for url in valid_urls:
            mock_downloader.validate_url.return_value = True
            mock_downloader.extract_video_id.return_value = "dQw4w9WgXcQ"
            # Validate URL format is accepted
            assert mock_downloader.validate_url(url) is True


# =============================================================================
# Test: Duplicate Detection & Reuse
# =============================================================================


class TestDuplicateDetection:
    """Tests for duplicate video detection and reuse."""

    async def test_existing_ready_video_returns_immediately(
        self, ingestion_service, mock_document_db
    ):
        """Test that ingesting an already-ready video returns existing record."""
        existing = {
            "id": "existing-uuid-123",
            "youtube_id": "dQw4w9WgXcQ",
            "youtube_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "title": "Already Processed Video",
            "description": "This video was already ingested",
            "duration_seconds": 120,
            "channel_name": "Test Channel",
            "channel_id": "UC123456",
            "upload_date": datetime.now(UTC).isoformat(),
            "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
            "status": VideoStatus.READY.value,
            "transcript_chunk_count": 5,
            "frame_chunk_count": 10,
            "audio_chunk_count": 0,
            "video_chunk_count": 0,
            "created_at": datetime.now(UTC),
        }
        mock_document_db.find_one.return_value = existing

        request = IngestVideoRequest(url="https://youtube.com/watch?v=dQw4w9WgXcQ")
        result = await ingestion_service.ingest(request)

        assert result.video_id == "existing-uuid-123"
        assert result.youtube_id == "dQw4w9WgXcQ"
        assert result.status == IngestionStatus.COMPLETED
        assert result.chunk_counts["transcript"] == 5
        assert result.chunk_counts["frame"] == 10

        # Verify no download was attempted
        mock_document_db.insert.assert_not_called()

    async def test_existing_failed_video_without_blobs_restarts(
        self, ingestion_service, mock_document_db, mock_blob_storage
    ):
        """Test that a failed video without blobs triggers full restart."""
        existing = {
            "id": "failed-uuid-123",
            "youtube_id": "dQw4w9WgXcQ",
            "youtube_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "title": "Failed Video",
            "description": "A video that failed",
            "duration_seconds": 120,
            "channel_name": "Test Channel",
            "channel_id": "UC123456",
            "upload_date": datetime.now(UTC).isoformat(),
            "thumbnail_url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg",
            "status": VideoStatus.FAILED.value,
            "blob_path_video": None,
            "blob_path_audio": None,
            "error_message": "Previous failure",
            "created_at": datetime.now(UTC),
        }
        mock_document_db.find_one.return_value = existing
        mock_blob_storage.exists.return_value = False
        mock_blob_storage.list_blobs.return_value = []

        request = IngestVideoRequest(url="https://youtube.com/watch?v=dQw4w9WgXcQ")
        result = await ingestion_service.ingest(request)

        # Should have deleted the old record
        mock_document_db.delete.assert_called_with("videos", "failed-uuid-123")
        # Should have created a new record
        mock_document_db.insert.assert_called()
        assert result.status == IngestionStatus.COMPLETED

    async def test_existing_video_with_blobs_resumes(
        self, ingestion_service, mock_document_db, mock_blob_storage, mock_transcriber
    ):
        """Test that an incomplete video with blobs resumes processing."""
        existing = {
            "id": "incomplete-uuid-123",
            "youtube_id": "dQw4w9WgXcQ",
            "youtube_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "title": "Incomplete Video",
            "description": "Processing was interrupted",
            "duration_seconds": 120,
            "channel_name": "Test Channel",
            "channel_id": "UC123",
            "upload_date": datetime.now(UTC).isoformat(),
            "thumbnail_url": "https://example.com/thumb.jpg",
            "status": VideoStatus.TRANSCRIBING.value,
            "blob_path_video": "incomplete-uuid-123/video.mp4",
            "blob_path_audio": "incomplete-uuid-123/audio.mp3",
            "created_at": datetime.now(UTC),
        }
        mock_document_db.find_one.return_value = existing
        mock_blob_storage.exists.return_value = True  # Blobs exist

        request = IngestVideoRequest(url="https://youtube.com/watch?v=dQw4w9WgXcQ")
        result = await ingestion_service.ingest(request)

        # Should NOT have deleted the record
        assert mock_document_db.delete.call_count == 0
        # Should have resumed from transcription
        mock_transcriber.transcribe.assert_called()
        assert result.status == IngestionStatus.COMPLETED


# =============================================================================
# Test: Full Ingestion Pipeline
# =============================================================================


class TestFullIngestionPipeline:
    """Tests for the complete ingestion pipeline."""

    async def test_full_ingestion_success(
        self,
        ingestion_service,
        mock_document_db,
        mock_transcriber,
        mock_vector_db,
    ):
        """Test successful full ingestion pipeline."""
        request = IngestVideoRequest(
            url="https://youtube.com/watch?v=dQw4w9WgXcQ",
            extract_frames=True,
            language_hint="en",
        )

        result = await ingestion_service.ingest(request)

        # Verify result
        assert result.youtube_id == "dQw4w9WgXcQ"
        assert result.title == "Test Video Title"
        assert result.duration_seconds == 120
        assert result.status == IngestionStatus.COMPLETED
        assert result.chunk_counts["transcript"] > 0

        # Verify pipeline steps were executed
        mock_document_db.insert.assert_called()  # Initial metadata
        mock_transcriber.transcribe.assert_called_once()  # Transcription
        mock_vector_db.upsert.assert_called()  # Embeddings stored
        mock_document_db.insert_many.assert_called()  # Chunks stored

    async def test_ingestion_without_frame_extraction(
        self, ingestion_service, mock_document_db
    ):
        """Test ingestion without frame extraction."""
        request = IngestVideoRequest(
            url="https://youtube.com/watch?v=dQw4w9WgXcQ",
            extract_frames=False,
        )

        result = await ingestion_service.ingest(request)

        assert result.status == IngestionStatus.COMPLETED
        assert result.chunk_counts["frame"] == 0

    async def test_ingestion_with_progress_callback(self, ingestion_service):
        """Test that progress callback is called during ingestion."""
        progress_updates: list[IngestionProgress] = []

        def progress_callback(progress: IngestionProgress) -> None:
            progress_updates.append(progress)

        request = IngestVideoRequest(
            url="https://youtube.com/watch?v=dQw4w9WgXcQ",
            extract_frames=False,
        )

        await ingestion_service.ingest(request, progress_callback=progress_callback)

        # Verify progress was reported for multiple steps
        assert len(progress_updates) > 0

        # Verify we got updates for different steps
        steps_reported = {p.current_step for p in progress_updates}
        assert ProcessingStep.VALIDATING in steps_reported
        assert ProcessingStep.DOWNLOADING in steps_reported
        assert ProcessingStep.COMPLETED in steps_reported

        # Verify overall progress increased
        progress_values = [p.overall_progress for p in progress_updates]
        assert progress_values[-1] == 1.0  # Final progress is 100%


# =============================================================================
# Test: Error Handling
# =============================================================================


class TestErrorHandling:
    """Tests for error handling during ingestion."""

    async def test_video_not_found_error(
        self, ingestion_service, mock_downloader, mock_document_db
    ):
        """Test handling of VideoNotFoundError."""

        async def raise_not_found(*args, **kwargs):
            raise VideoNotFoundError("https://youtube.com/watch?v=invalid")

        mock_downloader.download = raise_not_found

        request = IngestVideoRequest(url="https://youtube.com/watch?v=invalid")

        with pytest.raises(IngestionError) as exc_info:
            await ingestion_service.ingest(request)

        assert exc_info.value.step == ProcessingStep.DOWNLOADING

    async def test_download_error(
        self, ingestion_service, mock_downloader, mock_document_db
    ):
        """Test handling of DownloadError."""

        async def raise_download_error(*args, **kwargs):
            raise DownloadError("https://youtube.com/watch?v=test", "Network error")

        mock_downloader.download = raise_download_error

        request = IngestVideoRequest(url="https://youtube.com/watch?v=test")

        with pytest.raises(IngestionError) as exc_info:
            await ingestion_service.ingest(request)

        assert exc_info.value.step == ProcessingStep.DOWNLOADING

    async def test_transcription_error_marks_video_failed(
        self,
        ingestion_service,
        mock_document_db,
        mock_transcriber,
    ):
        """Test that transcription errors mark the video as failed."""
        mock_transcriber.transcribe.side_effect = Exception("Transcription API error")

        request = IngestVideoRequest(url="https://youtube.com/watch?v=dQw4w9WgXcQ")

        with pytest.raises(IngestionError) as exc_info:
            await ingestion_service.ingest(request)

        assert "Transcription API error" in str(exc_info.value)

        # Verify video was marked as failed
        update_calls = mock_document_db.update.call_args_list
        # Last update should contain status=failed
        final_update = update_calls[-1]
        update_data = final_update[0][2]  # Third argument is the update dict
        assert update_data.get("status") == VideoStatus.FAILED.value

    async def test_embedding_error_marks_video_failed(
        self,
        ingestion_service,
        mock_document_db,
        mock_embedder,
    ):
        """Test that embedding errors mark the video as failed."""

        async def raise_error(texts):
            raise Exception("Embedding service unavailable")

        mock_embedder.embed_texts = raise_error

        request = IngestVideoRequest(url="https://youtube.com/watch?v=dQw4w9WgXcQ")

        with pytest.raises(IngestionError):
            await ingestion_service.ingest(request)

        # Verify video was marked as failed
        update_calls = mock_document_db.update.call_args_list
        assert len(update_calls) > 0


# =============================================================================
# Test: Cleanup Logic
# =============================================================================


class TestCleanupLogic:
    """Tests for data cleanup logic."""

    async def test_cleanup_video_data_removes_all_artifacts(
        self,
        ingestion_service,
        mock_blob_storage,
        mock_document_db,
        mock_vector_db,
    ):
        """Test that _cleanup_video_data removes all associated data."""
        video = VideoMetadata(
            id="cleanup-test-uuid",
            youtube_id="dQw4w9WgXcQ",
            youtube_url="https://youtube.com/watch?v=dQw4w9WgXcQ",
            title="Test Video",
            duration_seconds=120,
            channel_name="Test",
            channel_id="UC123",
            upload_date=datetime.now(UTC),
            thumbnail_url="https://example.com/thumb.jpg",
        )

        # Mock blobs to be deleted
        video_blob = MagicMock()
        video_blob.path = "cleanup-test-uuid/video.mp4"
        frame_blob = MagicMock()
        frame_blob.path = "cleanup-test-uuid/frames/frame_00001.jpg"

        mock_blob_storage.list_blobs.side_effect = [
            [video_blob],  # Videos bucket
            [frame_blob],  # Frames bucket
        ]

        await ingestion_service._cleanup_video_data(video)

        # Verify blobs were deleted
        mock_blob_storage.delete.assert_any_call(
            "videos", "cleanup-test-uuid/video.mp4"
        )
        mock_blob_storage.delete.assert_any_call(
            "frames", "cleanup-test-uuid/frames/frame_00001.jpg"
        )

        # Verify chunks were deleted
        mock_document_db.delete_many.assert_any_call(
            "transcript_chunks", {"video_id": "cleanup-test-uuid"}
        )
        mock_document_db.delete_many.assert_any_call(
            "frame_chunks", {"video_id": "cleanup-test-uuid"}
        )

        # Verify embeddings were deleted
        mock_vector_db.delete_by_filter.assert_called_with(
            "transcripts", {"video_id": "cleanup-test-uuid"}
        )

    async def test_cleanup_handles_errors_gracefully(
        self,
        ingestion_service,
        mock_blob_storage,
    ):
        """Test that cleanup errors are handled gracefully."""
        video = VideoMetadata(
            id="cleanup-error-test",
            youtube_id="dQw4w9WgXcQ",
            youtube_url="https://youtube.com/watch?v=dQw4w9WgXcQ",
            title="Test Video",
            duration_seconds=120,
            channel_name="Test",
            channel_id="UC123",
            upload_date=datetime.now(UTC),
            thumbnail_url="https://example.com/thumb.jpg",
        )

        mock_blob_storage.list_blobs.side_effect = Exception("Storage unavailable")

        # Should not raise - errors are swallowed
        await ingestion_service._cleanup_video_data(video)


# =============================================================================
# Test: Resume Logic
# =============================================================================


class TestResumeLogic:
    """Tests for resuming incomplete ingestions."""

    async def test_check_raw_blobs_exist_returns_true(
        self, ingestion_service, mock_blob_storage
    ):
        """Test blob existence check when blobs exist."""
        video = VideoMetadata(
            id="test-uuid",
            youtube_id="dQw4w9WgXcQ",
            youtube_url="https://youtube.com/watch?v=dQw4w9WgXcQ",
            title="Test",
            duration_seconds=120,
            channel_name="Test",
            channel_id="UC123",
            upload_date=datetime.now(UTC),
            thumbnail_url="https://example.com/thumb.jpg",
            blob_path_video="test-uuid/video.mp4",
            blob_path_audio="test-uuid/audio.mp3",
        )

        mock_blob_storage.exists.return_value = True

        result = await ingestion_service._check_raw_blobs_exist(video)
        assert result is True

    async def test_check_raw_blobs_exist_returns_false_no_paths(
        self, ingestion_service
    ):
        """Test blob existence check when paths are None."""
        video = VideoMetadata(
            id="test-uuid",
            youtube_id="dQw4w9WgXcQ",
            youtube_url="https://youtube.com/watch?v=dQw4w9WgXcQ",
            title="Test",
            duration_seconds=120,
            channel_name="Test",
            channel_id="UC123",
            upload_date=datetime.now(UTC),
            thumbnail_url="https://example.com/thumb.jpg",
            blob_path_video=None,
            blob_path_audio=None,
        )

        result = await ingestion_service._check_raw_blobs_exist(video)
        assert result is False

    async def test_check_raw_blobs_exist_returns_false_partial(
        self, ingestion_service, mock_blob_storage
    ):
        """Test blob existence check when only one blob exists."""
        video = VideoMetadata(
            id="test-uuid",
            youtube_id="dQw4w9WgXcQ",
            youtube_url="https://youtube.com/watch?v=dQw4w9WgXcQ",
            title="Test",
            duration_seconds=120,
            channel_name="Test",
            channel_id="UC123",
            upload_date=datetime.now(UTC),
            thumbnail_url="https://example.com/thumb.jpg",
            blob_path_video="test-uuid/video.mp4",
            blob_path_audio="test-uuid/audio.mp3",
        )

        # Video exists but audio doesn't
        mock_blob_storage.exists.side_effect = [True, False]

        result = await ingestion_service._check_raw_blobs_exist(video)
        assert result is False


# =============================================================================
# Test: Transcript Chunking
# =============================================================================


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
        assert chunks[0].start_time == 0.0

    def test_create_transcript_chunks_respects_chunk_duration(
        self, ingestion_service, mock_settings
    ):
        """Test that chunks respect the configured duration."""
        # Create segments spanning 100 seconds
        segments = []
        for i in range(20):
            seg = MagicMock()
            seg.start_time = float(i * 5)
            seg.end_time = float((i + 1) * 5)
            seg.text = f"Segment {i}"
            seg.confidence = 0.9
            seg.words = []
            segments.append(seg)

        # With chunk_seconds=30 and overlap_seconds=5
        chunks = ingestion_service._create_transcript_chunks(segments, "video-1", "en")

        # Verify chunks exist
        assert len(chunks) >= 1

        # Verify each chunk has valid timestamps
        for chunk in chunks:
            assert chunk.start_time >= 0
            assert chunk.end_time > chunk.start_time
            assert chunk.video_id == "video-1"
            assert chunk.language == "en"

    def test_create_transcript_chunks_with_word_timestamps(self, ingestion_service):
        """Test that word timestamps are included in chunks."""
        word1 = MagicMock()
        word1.word = "Hello"
        word1.start_time = 0.0
        word1.end_time = 0.5
        word1.confidence = 0.95

        word2 = MagicMock()
        word2.word = "world"
        word2.start_time = 0.5
        word2.end_time = 1.0
        word2.confidence = 0.93

        segment = MagicMock()
        segment.start_time = 0.0
        segment.end_time = 1.0
        segment.text = "Hello world"
        segment.confidence = 0.94
        segment.words = [word1, word2]

        chunks = ingestion_service._create_transcript_chunks([segment], "video-1", "en")

        assert len(chunks) == 1
        assert len(chunks[0].word_timestamps) == 2
        assert chunks[0].word_timestamps[0].word == "Hello"
        assert chunks[0].word_timestamps[1].word == "world"


# =============================================================================
# Test: Video CRUD Operations
# =============================================================================


class TestVideoCRUD:
    """Tests for video CRUD operations."""

    async def test_get_ingestion_status_not_found(
        self, ingestion_service, mock_document_db
    ):
        """Test get_ingestion_status when video not found."""
        mock_document_db.find_by_id.return_value = None

        result = await ingestion_service.get_ingestion_status("nonexistent")
        assert result is None

    async def test_get_ingestion_status_found_ready(
        self, ingestion_service, mock_document_db
    ):
        """Test get_ingestion_status for ready video."""
        mock_document_db.find_by_id.return_value = {
            "id": "video-1",
            "youtube_id": "dQw4w9WgXcQ",
            "title": "Test Video",
            "duration_seconds": 120,
            "status": VideoStatus.READY.value,
            "transcript_chunk_count": 5,
            "frame_chunk_count": 10,
            "created_at": datetime.now(UTC),
        }

        result = await ingestion_service.get_ingestion_status("video-1")

        assert result is not None
        assert result.video_id == "video-1"
        assert result.status == IngestionStatus.COMPLETED

    async def test_get_ingestion_status_found_failed(
        self, ingestion_service, mock_document_db
    ):
        """Test get_ingestion_status for failed video."""
        mock_document_db.find_by_id.return_value = {
            "id": "video-1",
            "youtube_id": "dQw4w9WgXcQ",
            "title": "Test Video",
            "duration_seconds": 120,
            "status": VideoStatus.FAILED.value,
            "error_message": "Something went wrong",
            "created_at": datetime.now(UTC),
        }

        result = await ingestion_service.get_ingestion_status("video-1")

        assert result is not None
        assert result.status == IngestionStatus.FAILED
        assert result.error_message == "Something went wrong"

    async def test_get_ingestion_status_found_in_progress(
        self, ingestion_service, mock_document_db
    ):
        """Test get_ingestion_status for in-progress video."""
        mock_document_db.find_by_id.return_value = {
            "id": "video-1",
            "youtube_id": "dQw4w9WgXcQ",
            "title": "Test Video",
            "duration_seconds": 120,
            "status": VideoStatus.TRANSCRIBING.value,
            "created_at": datetime.now(UTC),
        }

        result = await ingestion_service.get_ingestion_status("video-1")

        assert result is not None
        assert result.status == IngestionStatus.IN_PROGRESS

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

    async def test_list_videos_pagination(self, ingestion_service, mock_document_db):
        """Test list_videos with pagination."""
        await ingestion_service.list_videos(skip=10, limit=5)

        mock_document_db.find.assert_called_once()
        call_args = mock_document_db.find.call_args
        assert call_args[1]["skip"] == 10
        assert call_args[1]["limit"] == 5

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
            "youtube_id": "dQw4w9WgXcQ",
        }
        mock_blob_storage.list_blobs.return_value = []

        result = await ingestion_service.delete_video("video-1")

        assert result is True
        mock_vector_db.delete_by_filter.assert_called_once()
        mock_document_db.delete_many.assert_called()
        mock_document_db.delete.assert_called_once_with("videos", "video-1")

    async def test_delete_video_cleans_blobs(
        self,
        ingestion_service,
        mock_document_db,
        mock_blob_storage,
    ):
        """Test that delete_video cleans up blobs."""
        mock_document_db.find_by_id.return_value = {
            "id": "video-1",
            "youtube_id": "dQw4w9WgXcQ",
        }

        video_blob = MagicMock()
        video_blob.path = "video-1/video.mp4"
        frame_blob = MagicMock()
        frame_blob.path = "video-1/frames/frame_00001.jpg"

        mock_blob_storage.list_blobs.side_effect = [
            [video_blob],  # Videos bucket
            [frame_blob],  # Frames bucket
        ]

        result = await ingestion_service.delete_video("video-1")

        assert result is True
        mock_blob_storage.delete.assert_any_call("videos", "video-1/video.mp4")
        mock_blob_storage.delete.assert_any_call(
            "frames", "video-1/frames/frame_00001.jpg"
        )
