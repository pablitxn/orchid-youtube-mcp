"""Unit tests for citation domain models."""

import pytest

from src.domain.models.chunk import Modality
from src.domain.models.citation import CitationGroup, SourceCitation, TimestampRange


class TestTimestampRange:
    """Tests for TimestampRange model."""

    def test_create(self):
        ts = TimestampRange(start_time=10.0, end_time=30.0)
        assert ts.start_time == 10.0
        assert ts.end_time == 30.0

    def test_duration_seconds(self):
        ts = TimestampRange(start_time=10.0, end_time=30.0)
        assert ts.duration_seconds == 20.0

    def test_format_display(self):
        ts = TimestampRange(start_time=65.0, end_time=125.0)
        assert ts.format_display() == "01:05 - 02:05"

    def test_format_display_long(self):
        ts = TimestampRange(start_time=3665.0, end_time=7325.0)
        assert ts.format_display_long() == "01:01:05 - 02:02:05"

    def test_to_youtube_url_param(self):
        ts = TimestampRange(start_time=125.7, end_time=150.0)
        assert ts.to_youtube_url_param() == "t=125"

    def test_contains(self):
        ts = TimestampRange(start_time=10.0, end_time=30.0)
        assert ts.contains(20.0) is True
        assert ts.contains(10.0) is True
        assert ts.contains(30.0) is True
        assert ts.contains(5.0) is False
        assert ts.contains(35.0) is False

    def test_overlaps(self):
        ts1 = TimestampRange(start_time=10.0, end_time=30.0)
        ts2 = TimestampRange(start_time=25.0, end_time=45.0)
        ts3 = TimestampRange(start_time=35.0, end_time=50.0)
        assert ts1.overlaps(ts2) is True
        assert ts1.overlaps(ts3) is False

    def test_merge(self):
        ts1 = TimestampRange(start_time=10.0, end_time=30.0)
        ts2 = TimestampRange(start_time=25.0, end_time=45.0)
        merged = ts1.merge(ts2)
        assert merged.start_time == 10.0
        assert merged.end_time == 45.0

    def test_from_seconds(self):
        ts = TimestampRange.from_seconds(10, 30)
        assert ts.start_time == 10.0
        assert ts.end_time == 30.0

    def test_invalid_range(self):
        with pytest.raises(ValueError):
            TimestampRange(start_time=30.0, end_time=10.0)

    def test_same_start_end_allowed(self):
        ts = TimestampRange(start_time=10.0, end_time=10.0)
        assert ts.duration_seconds == 0.0


class TestSourceCitation:
    """Tests for SourceCitation model."""

    @pytest.fixture
    def sample_citation(self) -> SourceCitation:
        return SourceCitation(
            video_id="video-123",
            chunk_ids=["chunk-1", "chunk-2"],
            modality=Modality.TRANSCRIPT,
            timestamp_range=TimestampRange(start_time=60.0, end_time=90.0),
            relevance_score=0.85,
            content_preview="The speaker discusses machine learning algorithms...",
        )

    def test_create(self, sample_citation):
        assert sample_citation.video_id == "video-123"
        assert len(sample_citation.chunk_ids) == 2
        assert sample_citation.relevance_score == 0.85

    def test_auto_id(self, sample_citation):
        assert sample_citation.id is not None
        assert len(sample_citation.id) == 36

    def test_youtube_url_with_timestamp(self, sample_citation):
        url = sample_citation.youtube_url_with_timestamp(
            "https://www.youtube.com/watch?v=abc123"
        )
        assert "t=60" in url
        assert "https://www.youtube.com/watch?v=abc123" in url

    def test_youtube_url_with_timestamp_no_params(self, sample_citation):
        url = sample_citation.youtube_url_with_timestamp("https://youtu.be/abc123")
        assert "?t=60" in url

    def test_format_for_display(self, sample_citation):
        display = sample_citation.format_for_display()
        assert "01:00 - 01:30" in display
        assert "machine learning" in display

    def test_is_transcript_citation(self, sample_citation):
        assert sample_citation.is_transcript_citation is True
        assert sample_citation.is_visual_citation is False

    def test_is_visual_citation(self):
        frame_citation = SourceCitation(
            video_id="video-123",
            chunk_ids=["frame-1"],
            modality=Modality.FRAME,
            timestamp_range=TimestampRange(start_time=30.0, end_time=30.0),
            relevance_score=0.75,
            content_preview="Frame showing a diagram",
        )
        assert frame_citation.is_visual_citation is True
        assert frame_citation.is_transcript_citation is False

    def test_chunk_ids_required(self):
        with pytest.raises(ValueError):
            SourceCitation(
                video_id="video-123",
                chunk_ids=[],
                modality=Modality.TRANSCRIPT,
                timestamp_range=TimestampRange(start_time=0, end_time=30),
                relevance_score=0.5,
                content_preview="Test",
            )

    def test_relevance_score_validation(self):
        with pytest.raises(ValueError):
            SourceCitation(
                video_id="video-123",
                chunk_ids=["chunk-1"],
                modality=Modality.TRANSCRIPT,
                timestamp_range=TimestampRange(start_time=0, end_time=30),
                relevance_score=1.5,
                content_preview="Test",
            )


class TestCitationGroup:
    """Tests for CitationGroup model."""

    @pytest.fixture
    def sample_citations(self) -> list[SourceCitation]:
        return [
            SourceCitation(
                video_id="video-123",
                chunk_ids=["chunk-1"],
                modality=Modality.TRANSCRIPT,
                timestamp_range=TimestampRange(start_time=10.0, end_time=30.0),
                relevance_score=0.9,
                content_preview="Highest relevance citation",
            ),
            SourceCitation(
                video_id="video-123",
                chunk_ids=["chunk-2"],
                modality=Modality.FRAME,
                timestamp_range=TimestampRange(start_time=60.0, end_time=60.0),
                relevance_score=0.7,
                content_preview="Frame citation",
            ),
            SourceCitation(
                video_id="video-123",
                chunk_ids=["chunk-3"],
                modality=Modality.TRANSCRIPT,
                timestamp_range=TimestampRange(start_time=120.0, end_time=150.0),
                relevance_score=0.4,
                content_preview="Low relevance citation",
            ),
        ]

    @pytest.fixture
    def citation_group(self, sample_citations: list[SourceCitation]) -> CitationGroup:
        return CitationGroup(
            citations=sample_citations,
            query="What is discussed in the video?",
            video_id="video-123",
        )

    def test_total_citations(self, citation_group):
        assert citation_group.total_citations == 3

    def test_citations_by_modality(self, citation_group):
        by_modality = citation_group.citations_by_modality
        assert len(by_modality[Modality.TRANSCRIPT]) == 2
        assert len(by_modality[Modality.FRAME]) == 1

    def test_top_citation(self, citation_group):
        top = citation_group.top_citation
        assert top is not None
        assert top.relevance_score == 0.9

    def test_top_citation_empty(self):
        group = CitationGroup(citations=[], query="Test", video_id="video-123")
        assert group.top_citation is None

    def test_get_citations_above_threshold(self, citation_group):
        above_05 = citation_group.get_citations_above_threshold(0.5)
        assert len(above_05) == 2

        above_08 = citation_group.get_citations_above_threshold(0.8)
        assert len(above_08) == 1

    def test_sorted_by_relevance(self, citation_group):
        sorted_desc = citation_group.sorted_by_relevance(descending=True)
        assert sorted_desc[0].relevance_score == 0.9
        assert sorted_desc[-1].relevance_score == 0.4

        sorted_asc = citation_group.sorted_by_relevance(descending=False)
        assert sorted_asc[0].relevance_score == 0.4

    def test_sorted_by_time(self, citation_group):
        sorted_time = citation_group.sorted_by_time()
        assert sorted_time[0].timestamp_range.start_time == 10.0
        assert sorted_time[-1].timestamp_range.start_time == 120.0
