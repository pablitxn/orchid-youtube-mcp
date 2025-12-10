"""Video management endpoints."""

from datetime import datetime
from enum import Enum
from typing import Annotated

from fastapi import APIRouter, Header, Query, status
from pydantic import BaseModel, Field

from src.api.dependencies import IngestionServiceDep
from src.api.middleware.error_handler import APIError
from src.application.dtos.ingestion import IngestionStatus
from src.domain.models.video import VideoStatus

router = APIRouter()


class VideoSortField(str, Enum):
    """Fields available for sorting videos."""

    CREATED_AT = "created_at"
    TITLE = "title"
    DURATION = "duration"


class SortOrder(str, Enum):
    """Sort order options."""

    ASC = "asc"
    DESC = "desc"


class VideoSummary(BaseModel):
    """Summary information for a video."""

    id: str = Field(description="Internal video UUID")
    youtube_id: str = Field(description="YouTube video ID")
    title: str = Field(description="Video title")
    duration_seconds: int = Field(description="Video duration in seconds")
    status: IngestionStatus = Field(description="Current status")
    chunk_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Number of chunks by modality",
    )
    created_at: datetime = Field(description="When the video was ingested")


class PaginationInfo(BaseModel):
    """Pagination metadata."""

    page: int = Field(ge=1, description="Current page number")
    page_size: int = Field(ge=1, le=100, description="Items per page")
    total_items: int = Field(ge=0, description="Total number of items")
    total_pages: int = Field(ge=0, description="Total number of pages")


class VideoListResponse(BaseModel):
    """Response for video listing."""

    videos: list[VideoSummary] = Field(description="List of videos")
    pagination: PaginationInfo = Field(description="Pagination metadata")


class DeleteResponse(BaseModel):
    """Response for video deletion."""

    success: bool = Field(description="Whether deletion was successful")
    video_id: str = Field(description="ID of deleted video")
    message: str = Field(description="Status message")


@router.get(
    "/videos",
    response_model=VideoListResponse,
    summary="List videos",
    description="List all indexed videos with optional filtering and pagination.",
)
async def list_videos(
    service: IngestionServiceDep,
    status_filter: Annotated[
        list[str] | None,
        Query(
            alias="status",
            description="Filter by status (ready, processing, failed)",
        ),
    ] = None,
    page: Annotated[
        int,
        Query(ge=1, description="Page number"),
    ] = 1,
    page_size: Annotated[
        int,
        Query(ge=1, le=100, description="Items per page"),
    ] = 20,
) -> VideoListResponse:
    """List indexed videos with pagination."""
    # Convert status filter to VideoStatus if provided
    video_status: VideoStatus | None = None
    if status_filter and len(status_filter) == 1:
        status_map = {
            "ready": VideoStatus.READY,
            "processing": VideoStatus.DOWNLOADING,
            "failed": VideoStatus.FAILED,
            "pending": VideoStatus.PENDING,
        }
        video_status = status_map.get(status_filter[0].lower())

    # Calculate skip from page
    skip = (page - 1) * page_size

    # Get videos from service
    videos = await service.list_videos(
        status=video_status,
        skip=skip,
        limit=page_size,
    )

    # Build response
    video_summaries = [
        VideoSummary(
            id=v.video_id,
            youtube_id=v.youtube_id,
            title=v.title,
            duration_seconds=v.duration_seconds,
            status=v.status,
            chunk_counts=v.chunk_counts,
            created_at=v.created_at,
        )
        for v in videos
    ]

    # For now, estimate total (proper implementation would count in DB)
    total_items = len(videos) + skip
    if len(videos) == page_size:
        total_items += 1  # There might be more

    total_pages = (total_items + page_size - 1) // page_size

    return VideoListResponse(
        videos=video_summaries,
        pagination=PaginationInfo(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        ),
    )


@router.get(
    "/videos/{video_id}",
    response_model=VideoSummary,
    summary="Get video details",
    description="Get detailed information about a specific video.",
)
async def get_video(
    video_id: str,
    service: IngestionServiceDep,
) -> VideoSummary:
    """Get details for a specific video."""
    result = await service.get_ingestion_status(video_id)

    if result is None:
        raise APIError(
            code="VIDEO_NOT_FOUND",
            message=f"Video with ID '{video_id}' was not found",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"video_id": video_id},
        )

    return VideoSummary(
        id=result.video_id,
        youtube_id=result.youtube_id,
        title=result.title,
        duration_seconds=result.duration_seconds,
        status=result.status,
        chunk_counts=result.chunk_counts,
        created_at=result.created_at,
    )


@router.delete(
    "/videos/{video_id}",
    response_model=DeleteResponse,
    summary="Delete video",
    description="Delete a video and all its associated data.",
)
async def delete_video(
    video_id: str,
    service: IngestionServiceDep,
    x_confirm_delete: Annotated[
        str | None,
        Header(description="Must be 'true' to confirm deletion"),
    ] = None,
) -> DeleteResponse:
    """Delete a video and all associated data.

    Requires X-Confirm-Delete header set to 'true'.
    """
    if x_confirm_delete != "true":
        raise APIError(
            code="CONFIRMATION_REQUIRED",
            message="Deletion requires X-Confirm-Delete header set to 'true'",
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Check if video exists first
    existing = await service.get_ingestion_status(video_id)
    if existing is None:
        raise APIError(
            code="VIDEO_NOT_FOUND",
            message=f"Video with ID '{video_id}' was not found",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"video_id": video_id},
        )

    # Delete the video
    deleted = await service.delete_video(video_id)

    if not deleted:
        raise APIError(
            code="DELETE_FAILED",
            message="Failed to delete video",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"video_id": video_id},
        )

    return DeleteResponse(
        success=True,
        video_id=video_id,
        message="Video and all associated data deleted successfully",
    )
