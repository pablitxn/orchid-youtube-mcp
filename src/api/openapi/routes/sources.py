"""Source retrieval endpoints."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, status
from pydantic import BaseModel, Field

from src.api.dependencies import QueryServiceDep
from src.api.middleware.error_handler import APIError
from src.application.dtos.query import (
    GetSourcesRequest,
    QueryModality,
    SourceArtifact,
    TimestampRangeDTO,
)

router = APIRouter()


class SourceDetailResponse(BaseModel):
    """Detailed source information for a citation."""

    citation_id: str = Field(description="Citation identifier")
    modality: QueryModality = Field(description="Source modality")
    timestamp_range: TimestampRangeDTO = Field(description="Time range in video")
    artifacts: dict[str, SourceArtifact] = Field(
        default_factory=dict,
        description="Available artifacts by type",
    )


class SourcesResponse(BaseModel):
    """Response with detailed source information."""

    sources: list[SourceDetailResponse] = Field(
        description="Detailed source information",
    )
    expires_at: datetime = Field(description="When presigned URLs expire")


@router.get(
    "/videos/{video_id}/sources",
    response_model=SourcesResponse,
    summary="Get source artifacts",
    description=(
        "Retrieve detailed source artifacts (transcripts, frames, audio clips) "
        "for specific citations from a query result."
    ),
)
async def get_sources(
    video_id: str,
    service: QueryServiceDep,
    citation_ids: Annotated[
        list[str],
        Query(
            description="Citation IDs to retrieve sources for",
            min_length=1,
        ),
    ],
    include_artifacts: Annotated[
        list[str] | None,
        Query(
            description="Artifact types to include",
            examples=["transcript_text", "thumbnail", "frame_image"],
        ),
    ] = None,
    url_expiry_minutes: Annotated[
        int,
        Query(
            ge=5,
            le=1440,
            description="How long presigned URLs should remain valid",
        ),
    ] = 60,
) -> SourcesResponse:
    """Get detailed source artifacts for citations.

    Returns transcript text, frame images, audio clips, or video segments
    for the specified citation IDs.
    """
    try:
        # Build internal request
        internal_request = GetSourcesRequest(
            citation_ids=citation_ids,
            include_artifacts=include_artifacts or ["transcript_text", "thumbnail"],
            url_expiry_minutes=url_expiry_minutes,
        )

        # Get sources
        result = await service.get_sources(video_id, internal_request)

        # Convert to API response
        return SourcesResponse(
            sources=[
                SourceDetailResponse(
                    citation_id=s.citation_id,
                    modality=s.modality,
                    timestamp_range=s.timestamp_range,
                    artifacts=s.artifacts,
                )
                for s in result.sources
            ],
            expires_at=result.expires_at,
        )

    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise APIError(
                code="VIDEO_NOT_FOUND",
                message=f"Video with ID '{video_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
                details={"video_id": video_id},
            ) from e
        raise APIError(
            code="SOURCES_ERROR",
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from e
