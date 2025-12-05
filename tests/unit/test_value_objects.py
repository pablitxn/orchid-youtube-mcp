"""Unit tests for domain value objects."""

import pytest

from src.domain.exceptions import InvalidYouTubeUrlException
from src.domain.value_objects import ChunkingConfig, YouTubeVideoId


class TestYouTubeVideoId:
    """Tests for YouTubeVideoId value object."""

    def test_valid_id(self):
        vid = YouTubeVideoId(value="dQw4w9WgXcQ")
        assert vid.value == "dQw4w9WgXcQ"

    def test_invalid_length_short(self):
        with pytest.raises(ValueError):
            YouTubeVideoId(value="abc")

    def test_invalid_length_long(self):
        with pytest.raises(ValueError):
            YouTubeVideoId(value="dQw4w9WgXcQextra")

    def test_invalid_characters(self):
        with pytest.raises(ValueError):
            YouTubeVideoId(value="dQw4w9Wg@cQ")

    def test_from_standard_url(self):
        vid = YouTubeVideoId.from_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
        assert vid.value == "dQw4w9WgXcQ"

    def test_from_short_url(self):
        vid = YouTubeVideoId.from_url("https://youtu.be/dQw4w9WgXcQ")
        assert vid.value == "dQw4w9WgXcQ"

    def test_from_embed_url(self):
        vid = YouTubeVideoId.from_url("https://www.youtube.com/embed/dQw4w9WgXcQ")
        assert vid.value == "dQw4w9WgXcQ"

    def test_from_shorts_url(self):
        vid = YouTubeVideoId.from_url("https://www.youtube.com/shorts/dQw4w9WgXcQ")
        assert vid.value == "dQw4w9WgXcQ"

    def test_from_url_with_params(self):
        vid = YouTubeVideoId.from_url(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42s&list=PLtest"
        )
        assert vid.value == "dQw4w9WgXcQ"

    def test_from_just_id(self):
        vid = YouTubeVideoId.from_url("dQw4w9WgXcQ")
        assert vid.value == "dQw4w9WgXcQ"

    def test_from_invalid_url(self):
        with pytest.raises(InvalidYouTubeUrlException) as exc_info:
            YouTubeVideoId.from_url("https://example.com/video")
        assert "Could not extract video ID" in exc_info.value.reason

    def test_from_empty_url(self):
        with pytest.raises(InvalidYouTubeUrlException):
            YouTubeVideoId.from_url("")

    def test_to_url(self):
        vid = YouTubeVideoId(value="dQw4w9WgXcQ")
        assert vid.to_url() == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    def test_to_url_short(self):
        vid = YouTubeVideoId(value="dQw4w9WgXcQ")
        assert vid.to_url(short=True) == "https://youtu.be/dQw4w9WgXcQ"

    def test_to_embed_url(self):
        vid = YouTubeVideoId(value="dQw4w9WgXcQ")
        assert vid.to_embed_url() == "https://www.youtube.com/embed/dQw4w9WgXcQ"

    def test_to_thumbnail_url(self):
        vid = YouTubeVideoId(value="dQw4w9WgXcQ")
        url = vid.to_thumbnail_url()
        assert "img.youtube.com" in url
        assert "dQw4w9WgXcQ" in url
        assert "hqdefault" in url

    def test_to_thumbnail_url_custom_quality(self):
        vid = YouTubeVideoId(value="dQw4w9WgXcQ")
        url = vid.to_thumbnail_url(quality="maxresdefault")
        assert "maxresdefault" in url

    def test_str(self):
        vid = YouTubeVideoId(value="dQw4w9WgXcQ")
        assert str(vid) == "dQw4w9WgXcQ"

    def test_equality(self):
        vid1 = YouTubeVideoId(value="dQw4w9WgXcQ")
        vid2 = YouTubeVideoId(value="dQw4w9WgXcQ")
        vid3 = YouTubeVideoId(value="abc123def45")
        assert vid1 == vid2
        assert vid1 != vid3
        assert vid1 == "dQw4w9WgXcQ"

    def test_hash(self):
        vid1 = YouTubeVideoId(value="dQw4w9WgXcQ")
        vid2 = YouTubeVideoId(value="dQw4w9WgXcQ")
        assert hash(vid1) == hash(vid2)
        # Can be used in sets
        video_set = {vid1, vid2}
        assert len(video_set) == 1


class TestChunkingConfig:
    """Tests for ChunkingConfig value object."""

    def test_default_values(self):
        config = ChunkingConfig()
        assert config.transcript_chunk_seconds == 30
        assert config.transcript_overlap_seconds == 5
        assert config.frame_interval_seconds == 2.0
        assert config.audio_chunk_seconds == 60
        assert config.video_chunk_seconds == 30
        assert config.video_chunk_overlap_seconds == 2
        assert config.video_chunk_max_size_mb == 20.0

    def test_custom_values(self):
        config = ChunkingConfig(
            transcript_chunk_seconds=60,
            frame_interval_seconds=5.0,
        )
        assert config.transcript_chunk_seconds == 60
        assert config.frame_interval_seconds == 5.0

    def test_transcript_chunk_seconds_validation(self):
        # Too small
        with pytest.raises(ValueError):
            ChunkingConfig(transcript_chunk_seconds=4)
        # Too large
        with pytest.raises(ValueError):
            ChunkingConfig(transcript_chunk_seconds=301)

    def test_frame_interval_validation(self):
        # Too small
        with pytest.raises(ValueError):
            ChunkingConfig(frame_interval_seconds=0.4)
        # Too large
        with pytest.raises(ValueError):
            ChunkingConfig(frame_interval_seconds=61)

    def test_calculate_transcript_chunks(self):
        config = ChunkingConfig(
            transcript_chunk_seconds=30,
            transcript_overlap_seconds=5,
        )
        # 60 seconds video with 30s chunks and 5s overlap = step of 25s
        # First chunk: 0-30, second chunk: 25-55, third chunk: 50-80 (exceeds)
        # Should be about 2-3 chunks
        count = config.calculate_transcript_chunks(60)
        assert count >= 2

    def test_calculate_transcript_chunks_zero_duration(self):
        config = ChunkingConfig()
        assert config.calculate_transcript_chunks(0) == 0
        assert config.calculate_transcript_chunks(-10) == 0

    def test_calculate_frame_count(self):
        config = ChunkingConfig(frame_interval_seconds=2.0)
        # 60 seconds / 2 seconds = 30 frames
        assert config.calculate_frame_count(60) == 30

    def test_calculate_frame_count_zero_duration(self):
        config = ChunkingConfig()
        assert config.calculate_frame_count(0) == 0

    def test_calculate_video_chunks(self):
        config = ChunkingConfig(
            video_chunk_seconds=30,
            video_chunk_overlap_seconds=2,
        )
        count = config.calculate_video_chunks(120)
        # Step = 28s, chunks needed for 120s
        assert count >= 4
