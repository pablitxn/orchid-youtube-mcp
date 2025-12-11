"""Unit tests for Application DTOs."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from src.application.dtos.ingestion import (
    IngestionProgress,
    IngestionStatus,
    IngestVideoRequest,
    IngestVideoResponse,
    ProcessingStep,
)
from src.application.dtos.query import (
    CitationDTO,
    GetSourcesRequest,
    QueryMetadata,
    QueryModality,
    QueryVideoRequest,
    QueryVideoResponse,
    SourceArtifact,
    SourceDetail,
    SourcesResponse,
    TimestampRangeDTO,
)


class TestIngestVideoRequest:
    """Tests for IngestVideoRequest DTO."""

    def test_valid_youtube_url(self):
        """Test with valid YouTube URL."""
        request = IngestVideoRequest(url="https://youtube.com/watch?v=test123")
        assert request.url == "https://youtube.com/watch?v=test123"

    def test_default_values(self):
        """Test default values are set correctly."""
        request = IngestVideoRequest(url="https://youtube.com/watch?v=test")
        assert request.extract_frames is True
        assert request.extract_audio_chunks is False
        assert request.extract_video_chunks is False
        assert request.language_hint is None
        assert request.max_resolution is None

    def test_custom_options(self):
        """Test custom options."""
        request = IngestVideoRequest(
            url="https://youtube.com/watch?v=test",
            language_hint="es",
            extract_frames=False,
            max_resolution="720p",
        )
        assert request.language_hint == "es"
        assert request.extract_frames is False
        assert request.max_resolution == "720p"


class TestIngestVideoResponse:
    """Tests for IngestVideoResponse DTO."""

    def test_completed_response(self):
        """Test completed ingestion response."""
        response = IngestVideoResponse(
            video_id="uuid-1234",
            youtube_id="test123",
            title="Test Video",
            duration_seconds=120,
            status=IngestionStatus.COMPLETED,
            chunk_counts={"transcript": 10, "frame": 50},
            created_at=datetime.now(UTC),
        )
        assert response.status == IngestionStatus.COMPLETED
        assert response.chunk_counts["transcript"] == 10

    def test_failed_response_with_error(self):
        """Test failed ingestion response with error message."""
        response = IngestVideoResponse(
            video_id="uuid-1234",
            youtube_id="test123",
            title="Test Video",
            duration_seconds=120,
            status=IngestionStatus.FAILED,
            error_message="Download failed",
            chunk_counts={},
            created_at=datetime.now(UTC),
        )
        assert response.status == IngestionStatus.FAILED
        assert response.error_message == "Download failed"


class TestIngestionProgress:
    """Tests for IngestionProgress DTO."""

    def test_progress_validation(self):
        """Test progress values are validated."""
        progress = IngestionProgress(
            current_step=ProcessingStep.DOWNLOADING,
            step_progress=0.5,
            overall_progress=0.25,
            message="Downloading video...",
            started_at=datetime.now(UTC),
        )
        assert 0 <= progress.step_progress <= 1
        assert 0 <= progress.overall_progress <= 1


class TestQueryVideoRequest:
    """Tests for QueryVideoRequest DTO."""

    def test_minimal_request(self):
        """Test minimal query request."""
        request = QueryVideoRequest(query="What is this video about?")
        assert request.query == "What is this video about?"
        assert QueryModality.TRANSCRIPT in request.modalities

    def test_query_length_validation(self):
        """Test query length validation."""
        with pytest.raises(ValidationError):
            QueryVideoRequest(query="")  # Too short

    def test_max_citations_validation(self):
        """Test max_citations bounds."""
        with pytest.raises(ValidationError):
            QueryVideoRequest(query="test", max_citations=0)

        with pytest.raises(ValidationError):
            QueryVideoRequest(query="test", max_citations=25)

    def test_similarity_threshold_validation(self):
        """Test similarity threshold bounds."""
        with pytest.raises(ValidationError):
            QueryVideoRequest(query="test", similarity_threshold=-0.1)

        with pytest.raises(ValidationError):
            QueryVideoRequest(query="test", similarity_threshold=1.5)

    def test_all_modalities(self):
        """Test request with all modalities."""
        request = QueryVideoRequest(
            query="test",
            modalities=[
                QueryModality.TRANSCRIPT,
                QueryModality.FRAME,
                QueryModality.AUDIO,
                QueryModality.VIDEO,
            ],
        )
        assert len(request.modalities) == 4


class TestQueryVideoResponse:
    """Tests for QueryVideoResponse DTO."""

    def test_complete_response(self):
        """Test complete query response."""
        response = QueryVideoResponse(
            answer="The video discusses machine learning.",
            reasoning="Based on transcript segments mentioning ML concepts.",
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
                    content_preview="In this video we discuss...",
                    relevance_score=0.9,
                    youtube_url="https://youtube.com/watch?v=test&t=10",
                )
            ],
            query_metadata=QueryMetadata(
                video_id="video-1",
                video_title="ML Tutorial",
                modalities_searched=[QueryModality.TRANSCRIPT],
                chunks_analyzed=5,
                processing_time_ms=150,
            ),
        )
        assert response.confidence == 0.85
        assert len(response.citations) == 1

    def test_confidence_bounds(self):
        """Test confidence score bounds."""
        with pytest.raises(ValidationError):
            QueryVideoResponse(
                answer="test",
                confidence=1.5,  # Invalid
                citations=[],
                query_metadata=QueryMetadata(
                    video_id="v1",
                    video_title="t",
                    modalities_searched=[],
                    chunks_analyzed=0,
                    processing_time_ms=0,
                ),
            )


class TestTimestampRangeDTO:
    """Tests for TimestampRangeDTO."""

    def test_valid_range(self):
        """Test valid timestamp range."""
        ts = TimestampRangeDTO(
            start_time=10.5,
            end_time=45.0,
            display="00:10 - 00:45",
        )
        assert ts.start_time == 10.5
        assert ts.end_time == 45.0

    def test_negative_time_validation(self):
        """Test that negative times are rejected."""
        with pytest.raises(ValidationError):
            TimestampRangeDTO(
                start_time=-5.0,
                end_time=10.0,
                display="invalid",
            )


class TestGetSourcesRequest:
    """Tests for GetSourcesRequest DTO."""

    def test_minimal_request(self):
        """Test minimal sources request."""
        request = GetSourcesRequest(citation_ids=["chunk-1"])
        assert len(request.citation_ids) == 1
        assert "transcript_text" in request.include_artifacts

    def test_empty_citation_ids_rejected(self):
        """Test that empty citation_ids list is rejected."""
        with pytest.raises(ValidationError):
            GetSourcesRequest(citation_ids=[])

    def test_url_expiry_bounds(self):
        """Test URL expiry validation."""
        with pytest.raises(ValidationError):
            GetSourcesRequest(citation_ids=["c1"], url_expiry_minutes=1)  # Too low

        with pytest.raises(ValidationError):
            GetSourcesRequest(citation_ids=["c1"], url_expiry_minutes=2000)  # Too high


class TestSourcesResponse:
    """Tests for SourcesResponse DTO."""

    def test_complete_response(self):
        """Test complete sources response."""
        response = SourcesResponse(
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
                            content="This is the transcript...",
                        ),
                        "thumbnail": SourceArtifact(
                            type="thumbnail",
                            url="https://storage.example.com/thumb.jpg",
                        ),
                    },
                )
            ],
            expires_at=datetime.now(UTC),
        )
        assert len(response.sources) == 1
        assert "transcript_text" in response.sources[0].artifacts


class TestCitationDTO:
    """Tests for CitationDTO."""

    def test_relevance_score_bounds(self):
        """Test relevance score validation."""
        with pytest.raises(ValidationError):
            CitationDTO(
                id="c1",
                modality=QueryModality.TRANSCRIPT,
                timestamp_range=TimestampRangeDTO(
                    start_time=0, end_time=10, display="0-10"
                ),
                content_preview="test",
                relevance_score=1.5,  # Invalid
            )
