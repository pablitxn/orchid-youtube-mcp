"""Unit tests for chunk domain models."""

import pytest

from src.domain.models.chunk import (
    AudioChunk,
    FrameChunk,
    Modality,
    TranscriptChunk,
    VideoChunk,
    WordTimestamp,
)


class TestModality:
    """Tests for Modality enum."""

    def test_values(self):
        assert Modality.TRANSCRIPT == "transcript"
        assert Modality.FRAME == "frame"
        assert Modality.AUDIO == "audio"
        assert Modality.VIDEO == "video"


class TestWordTimestamp:
    """Tests for WordTimestamp model."""

    def test_create(self):
        word = WordTimestamp(
            word="hello",
            start_time=1.5,
            end_time=2.0,
            confidence=0.95,
        )
        assert word.word == "hello"
        assert word.start_time == 1.5
        assert word.end_time == 2.0
        assert word.confidence == 0.95

    def test_confidence_validation(self):
        with pytest.raises(ValueError):
            WordTimestamp(word="test", start_time=0, end_time=1, confidence=1.5)
        with pytest.raises(ValueError):
            WordTimestamp(word="test", start_time=0, end_time=1, confidence=-0.1)


class TestTranscriptChunk:
    """Tests for TranscriptChunk model."""

    @pytest.fixture
    def sample_chunk(self) -> TranscriptChunk:
        return TranscriptChunk(
            video_id="video-123",
            start_time=10.0,
            end_time=40.0,
            text="This is a sample transcript text.",
            language="en",
            confidence=0.92,
            word_timestamps=[
                WordTimestamp(
                    word="This", start_time=10.0, end_time=10.5, confidence=0.95
                ),
                WordTimestamp(
                    word="is", start_time=10.5, end_time=10.7, confidence=0.98
                ),
                WordTimestamp(
                    word="sample", start_time=11.0, end_time=11.5, confidence=0.90
                ),
            ],
        )

    def test_modality_is_transcript(self, sample_chunk):
        assert sample_chunk.modality == Modality.TRANSCRIPT

    def test_duration_seconds(self, sample_chunk):
        assert sample_chunk.duration_seconds == 30.0

    def test_contains_timestamp(self, sample_chunk):
        assert sample_chunk.contains_timestamp(25.0) is True
        assert sample_chunk.contains_timestamp(5.0) is False
        assert sample_chunk.contains_timestamp(50.0) is False

    def test_overlaps_with(self, sample_chunk):
        other = TranscriptChunk(
            video_id="video-123",
            start_time=35.0,
            end_time=60.0,
            text="Other text",
            language="en",
            confidence=0.9,
        )
        assert sample_chunk.overlaps_with(other) is True

        non_overlapping = TranscriptChunk(
            video_id="video-123",
            start_time=50.0,
            end_time=80.0,
            text="Non-overlapping",
            language="en",
            confidence=0.9,
        )
        assert sample_chunk.overlaps_with(non_overlapping) is False

    def test_get_word_at_timestamp(self, sample_chunk):
        assert sample_chunk.get_word_at_timestamp(10.3) == "This"
        assert sample_chunk.get_word_at_timestamp(10.6) == "is"
        assert sample_chunk.get_word_at_timestamp(100.0) is None

    def test_get_text_in_range(self, sample_chunk):
        text = sample_chunk.get_text_in_range(10.0, 11.0)
        assert "This" in text
        assert "is" in text

    def test_word_count(self, sample_chunk):
        assert sample_chunk.word_count == 3

    def test_format_time_range(self, sample_chunk):
        assert sample_chunk.format_time_range() == "00:10 - 00:40"


class TestFrameChunk:
    """Tests for FrameChunk model."""

    @pytest.fixture
    def sample_frame(self) -> FrameChunk:
        return FrameChunk(
            video_id="video-123",
            start_time=15.0,
            end_time=15.0,
            frame_number=7,
            blob_path="frames/video-123/frame_007.jpg",
            thumbnail_path="frames/video-123/thumb_007.jpg",
            width=1920,
            height=1080,
        )

    def test_modality_is_frame(self, sample_frame):
        assert sample_frame.modality == Modality.FRAME

    def test_aspect_ratio(self, sample_frame):
        assert sample_frame.aspect_ratio == pytest.approx(1920 / 1080)

    def test_resolution(self, sample_frame):
        assert sample_frame.resolution == "1920x1080"

    def test_with_description(self, sample_frame):
        described = sample_frame.with_description("A person speaking on stage")
        assert described.description == "A person speaking on stage"
        assert sample_frame.description is None  # original unchanged

    def test_dimensions_validation(self):
        with pytest.raises(ValueError):
            FrameChunk(
                video_id="video-123",
                start_time=0,
                end_time=0,
                frame_number=0,
                blob_path="test.jpg",
                thumbnail_path="thumb.jpg",
                width=0,
                height=1080,
            )


class TestAudioChunk:
    """Tests for AudioChunk model."""

    @pytest.fixture
    def sample_audio(self) -> AudioChunk:
        return AudioChunk(
            video_id="video-123",
            start_time=0.0,
            end_time=60.0,
            blob_path="audio/video-123/chunk_0.mp3",
        )

    def test_modality_is_audio(self, sample_audio):
        assert sample_audio.modality == Modality.AUDIO

    def test_default_values(self, sample_audio):
        assert sample_audio.format == "mp3"
        assert sample_audio.sample_rate == 44100
        assert sample_audio.channels == 1

    def test_is_stereo(self, sample_audio):
        assert sample_audio.is_stereo is False
        stereo = AudioChunk(
            video_id="video-123",
            start_time=0,
            end_time=60,
            blob_path="audio.mp3",
            channels=2,
        )
        assert stereo.is_stereo is True


class TestVideoChunk:
    """Tests for VideoChunk model."""

    @pytest.fixture
    def sample_video_chunk(self) -> VideoChunk:
        return VideoChunk(
            video_id="video-123",
            start_time=30.0,
            end_time=60.0,
            blob_path="video/video-123/chunk_1.mp4",
            thumbnail_path="video/video-123/thumb_1.jpg",
            width=1920,
            height=1080,
            fps=30.0,
            size_bytes=10 * 1024 * 1024,  # 10 MB
        )

    def test_modality_is_video(self, sample_video_chunk):
        assert sample_video_chunk.modality == Modality.VIDEO

    def test_aspect_ratio(self, sample_video_chunk):
        assert sample_video_chunk.aspect_ratio == pytest.approx(1920 / 1080)

    def test_resolution(self, sample_video_chunk):
        assert sample_video_chunk.resolution == "1920x1080"

    def test_size_mb(self, sample_video_chunk):
        assert sample_video_chunk.size_mb == 10.0

    def test_is_within_size_limit(self, sample_video_chunk):
        assert sample_video_chunk.is_within_size_limit(20.0) is True
        assert sample_video_chunk.is_within_size_limit(5.0) is False

    def test_frame_count(self, sample_video_chunk):
        # 30 seconds * 30 fps = 900 frames
        assert sample_video_chunk.frame_count == 900

    def test_with_description(self, sample_video_chunk):
        described = sample_video_chunk.with_description("Person walking")
        assert described.description == "Person walking"

    def test_default_values(self, sample_video_chunk):
        assert sample_video_chunk.format == "mp4"
        assert sample_video_chunk.codec == "h264"
        assert sample_video_chunk.has_audio is True
