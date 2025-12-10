"""Video query endpoints."""

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from src.api.dependencies import QueryServiceDep
from src.api.middleware.error_handler import APIError
from src.application.dtos.query import (
    CitationDTO,
    QueryMetadata,
    QueryModality,
    QueryVideoRequest,
)

router = APIRouter()


class QueryRequest(BaseModel):
    """API request model for video query."""

    query: str = Field(
        min_length=1,
        max_length=1000,
        description="Natural language question about the video content",
        examples=["What does the speaker say about testing?"],
    )
    modalities: list[QueryModality] = Field(
        default=[QueryModality.TRANSCRIPT, QueryModality.FRAME],
        description="Which modalities to search across",
    )
    max_citations: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Maximum number of citations to return",
    )
    include_reasoning: bool = Field(
        default=True,
        description="Whether to include explanation of reasoning",
    )


class QueryResponse(BaseModel):
    """API response model for video query."""

    answer: str = Field(description="Answer to the query based on video content")
    reasoning: str | None = Field(
        default=None,
        description="Explanation of how the answer was derived",
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Confidence score for the answer",
    )
    citations: list[CitationDTO] = Field(
        default_factory=list,
        description="Source citations supporting the answer",
    )
    query_metadata: QueryMetadata = Field(
        description="Information about query execution",
    )


@router.post(
    "/videos/{video_id}/query",
    response_model=QueryResponse,
    summary="Query video content",
    description=(
        "Ask a natural language question about the content of an indexed video. "
        "Returns an answer with citations to specific timestamps."
    ),
)
async def query_video(
    video_id: str,
    request: QueryRequest,
    service: QueryServiceDep,
) -> QueryResponse:
    """Query video content with natural language.

    Performs semantic search across video transcripts and frames,
    then uses LLM to generate an answer with citations.
    """
    try:
        # Convert to internal request
        internal_request = QueryVideoRequest(
            query=request.query,
            modalities=request.modalities,
            max_citations=request.max_citations,
            include_reasoning=request.include_reasoning,
        )

        # Execute query
        result = await service.query(video_id, internal_request)

        return QueryResponse(
            answer=result.answer,
            reasoning=result.reasoning,
            confidence=result.confidence,
            citations=result.citations,
            query_metadata=result.query_metadata,
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
        if "not ready" in error_msg.lower():
            raise APIError(
                code="VIDEO_NOT_READY",
                message="Video is still being processed",
                status_code=status.HTTP_409_CONFLICT,
                details={"video_id": video_id},
            ) from e
        raise APIError(
            code="QUERY_ERROR",
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from e
