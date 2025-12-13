"""Video ingestion endpoints."""

import contextlib

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from src.api.dependencies import IngestionServiceDep
from src.application.dtos.ingestion import (
    IngestionStatus,
    IngestVideoRequest,
)

router = APIRouter()


class IngestRequest(BaseModel):
    """API request model for video ingestion."""

    youtube_url: str = Field(
        description="YouTube video URL to ingest",
        examples=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )
    extract_frames: bool = Field(
        default=True,
        description="Whether to extract video frames for visual analysis",
    )
    extract_audio_chunks: bool = Field(
        default=True,
        description="Whether to create separate audio chunks",
    )
    extract_video_chunks: bool = Field(
        default=False,
        description="Whether to create video segment chunks",
    )
    language_hint: str | None = Field(
        default=None,
        description="Expected language (ISO 639-1) for transcription",
        examples=["en", "es", "fr"],
    )
    max_resolution: int = Field(
        default=720,
        ge=144,
        le=2160,
        description="Maximum video resolution to download",
    )


class IngestResponse(BaseModel):
    """API response model for video ingestion."""

    video_id: str = Field(description="Internal UUID for the video")
    youtube_id: str = Field(description="YouTube video ID")
    title: str = Field(description="Video title")
    duration_seconds: int = Field(description="Video duration in seconds")
    status: IngestionStatus = Field(description="Current ingestion status")
    message: str = Field(description="Status message")


class StatusResponse(BaseModel):
    """API response model for ingestion status."""

    video_id: str = Field(description="Internal UUID for the video")
    youtube_id: str = Field(description="YouTube video ID")
    title: str = Field(description="Video title")
    status: IngestionStatus = Field(description="Current ingestion status")
    progress_percent: int = Field(
        ge=0,
        le=100,
        description="Overall progress percentage",
    )
    chunk_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Number of chunks created by modality",
    )
    error_message: str | None = Field(
        default=None,
        description="Error details if failed",
    )


async def _run_ingestion(
    service: IngestionServiceDep,
    request: IngestVideoRequest,
) -> None:
    """Background task to run ingestion."""
    with contextlib.suppress(Exception):
        await service.ingest(request)


@router.post(
    "/videos/ingest",
    response_model=IngestResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Ingest a YouTube video",
    description=(
        "Start ingesting a YouTube video for semantic search. "
        "The video will be downloaded, transcribed, and indexed asynchronously."
    ),
)
async def ingest_video(
    request: IngestRequest,
    service: IngestionServiceDep,
) -> IngestResponse:
    """Start video ingestion process.

    Returns immediately with video ID while processing continues in background.
    """
    # Convert to internal request format
    internal_request = IngestVideoRequest(
        url=request.youtube_url,
        language_hint=request.language_hint,
        extract_frames=request.extract_frames,
        extract_audio_chunks=request.extract_audio_chunks,
        extract_video_chunks=request.extract_video_chunks,
        max_resolution=request.max_resolution,
    )

    # Start ingestion (this validates URL and gets initial metadata)
    # For now, run synchronously to get initial response
    # Full processing happens in background
    result = await service.ingest(internal_request)

    return IngestResponse(
        video_id=result.video_id,
        youtube_id=result.youtube_id,
        title=result.title,
        duration_seconds=result.duration_seconds,
        status=result.status,
        message=_get_status_message(result.status),
    )


@router.get(
    "/videos/{video_id}/status",
    response_model=StatusResponse,
    summary="Get ingestion status",
    description="Check the current processing status of a video ingestion job.",
)
async def get_ingestion_status(
    video_id: str,
    service: IngestionServiceDep,
) -> StatusResponse:
    """Get current ingestion status for a video."""
    result = await service.get_ingestion_status(video_id)

    if result is None:
        from src.api.middleware.error_handler import APIError

        raise APIError(
            code="VIDEO_NOT_FOUND",
            message=f"Video with ID '{video_id}' was not found",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"video_id": video_id},
        )

    # Calculate progress percentage based on status
    progress_percent = _calculate_progress(result.status)

    return StatusResponse(
        video_id=result.video_id,
        youtube_id=result.youtube_id,
        title=result.title,
        status=result.status,
        progress_percent=progress_percent,
        chunk_counts=result.chunk_counts,
        error_message=result.error_message,
    )


def _get_status_message(status: IngestionStatus) -> str:
    """Get human-readable status message."""
    messages = {
        IngestionStatus.PENDING: "Video ingestion queued",
        IngestionStatus.IN_PROGRESS: "Video is being processed",
        IngestionStatus.COMPLETED: "Video ingestion completed successfully",
        IngestionStatus.FAILED: "Video ingestion failed",
    }
    return messages.get(status, "Unknown status")


def _calculate_progress(status: IngestionStatus) -> int:
    """Calculate progress percentage from status."""
    if status == IngestionStatus.PENDING:
        return 0
    if status == IngestionStatus.IN_PROGRESS:
        return 50  # Approximate mid-progress
    if status == IngestionStatus.COMPLETED:
        return 100
    return 0  # Failed
