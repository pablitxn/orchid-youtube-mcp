"""Unit tests for VideoMetadata model."""

from datetime import UTC, datetime

import pytest

from src.domain.models.video import VideoMetadata, VideoStatus


class TestVideoStatus:
    """Tests for VideoStatus enum."""

    def test_values(self):
        assert VideoStatus.PENDING == "pending"
        assert VideoStatus.DOWNLOADING == "downloading"
        assert VideoStatus.TRANSCRIBING == "transcribing"
        assert VideoStatus.EXTRACTING == "extracting"
        assert VideoStatus.EMBEDDING == "embedding"
        assert VideoStatus.READY == "ready"
        assert VideoStatus.FAILED == "failed"

    def test_string_conversion(self):
        # str(Enum) class gives "EnumName.VALUE", but .value gives the string
        assert VideoStatus.READY.value == "ready"
        # Can be used directly in string contexts due to str inheritance
        assert f"{VideoStatus.READY.value}" == "ready"


class TestVideoMetadata:
    """Tests for VideoMetadata model."""

    @pytest.fixture
    def sample_video(self) -> VideoMetadata:
        """Create a sample video for testing."""
        return VideoMetadata(
            youtube_id="dQw4w9WgXcQ",
            youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            title="Sample Video",
            description="A test video",
            duration_seconds=212,
            channel_name="Test Channel",
            channel_id="UC123456",
            upload_date=datetime(2020, 1, 1, tzinfo=UTC),
            thumbnail_url="https://img.youtube.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
        )

    def test_create_with_required_fields(self, sample_video):
        assert sample_video.youtube_id == "dQw4w9WgXcQ"
        assert sample_video.title == "Sample Video"
        assert sample_video.duration_seconds == 212
        assert sample_video.status == VideoStatus.PENDING

    def test_auto_generated_id(self, sample_video):
        assert sample_video.id is not None
        assert len(sample_video.id) == 36  # UUID format

    def test_auto_timestamps(self, sample_video):
        assert sample_video.created_at is not None
        assert sample_video.updated_at is not None

    def test_default_counts(self, sample_video):
        assert sample_video.transcript_chunk_count == 0
        assert sample_video.frame_chunk_count == 0
        assert sample_video.audio_chunk_count == 0
        assert sample_video.video_chunk_count == 0

    def test_is_ready(self, sample_video):
        assert sample_video.is_ready is False
        ready_video = sample_video.transition_to(VideoStatus.READY)
        assert ready_video.is_ready is True

    def test_is_failed(self, sample_video):
        assert sample_video.is_failed is False
        failed_video = sample_video.mark_failed("Test error")
        assert failed_video.is_failed is True

    def test_is_processing(self, sample_video):
        assert sample_video.is_processing is False
        downloading = sample_video.transition_to(VideoStatus.DOWNLOADING)
        assert downloading.is_processing is True

    def test_total_chunk_count(self):
        video = VideoMetadata(
            youtube_id="dQw4w9WgXcQ",
            youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            title="Test",
            duration_seconds=100,
            channel_name="Test",
            channel_id="UC123",
            upload_date=datetime(2020, 1, 1, tzinfo=UTC),
            thumbnail_url="https://example.com/thumb.jpg",
            transcript_chunk_count=10,
            frame_chunk_count=20,
            audio_chunk_count=5,
            video_chunk_count=3,
        )
        assert video.total_chunk_count == 38

    def test_duration_formatted_minutes(self, sample_video):
        # 212 seconds = 3:32
        assert sample_video.duration_formatted == "3:32"

    def test_duration_formatted_hours(self):
        video = VideoMetadata(
            youtube_id="dQw4w9WgXcQ",
            youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            title="Long Video",
            duration_seconds=3723,  # 1:02:03
            channel_name="Test",
            channel_id="UC123",
            upload_date=datetime(2020, 1, 1, tzinfo=UTC),
            thumbnail_url="https://example.com/thumb.jpg",
        )
        assert video.duration_formatted == "1:02:03"

    def test_transition_to(self, sample_video):
        downloading = sample_video.transition_to(VideoStatus.DOWNLOADING)
        assert downloading.status == VideoStatus.DOWNLOADING
        assert downloading.id == sample_video.id
        assert downloading.updated_at > sample_video.updated_at

    def test_transition_clears_error_message(self, sample_video):
        failed = sample_video.mark_failed("Some error")
        assert failed.error_message == "Some error"

        retrying = failed.transition_to(VideoStatus.DOWNLOADING)
        assert retrying.error_message is None

    def test_mark_failed(self, sample_video):
        failed = sample_video.mark_failed("Connection timeout")
        assert failed.status == VideoStatus.FAILED
        assert failed.error_message == "Connection timeout"

    def test_update_chunk_counts(self, sample_video):
        updated = sample_video.update_chunk_counts(
            transcript=10,
            frame=50,
        )
        assert updated.transcript_chunk_count == 10
        assert updated.frame_chunk_count == 50
        assert updated.audio_chunk_count == 0  # unchanged
        assert updated.updated_at > sample_video.updated_at

    def test_immutability(self, sample_video):
        """Verify that transition methods return new instances."""
        original_id = id(sample_video)
        transitioned = sample_video.transition_to(VideoStatus.DOWNLOADING)
        assert id(transitioned) != original_id

    def test_duration_validation(self):
        with pytest.raises(ValueError):
            VideoMetadata(
                youtube_id="dQw4w9WgXcQ",
                youtube_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
                title="Test",
                duration_seconds=-1,
                channel_name="Test",
                channel_id="UC123",
                upload_date=datetime(2020, 1, 1, tzinfo=UTC),
                thumbnail_url="https://example.com/thumb.jpg",
            )
