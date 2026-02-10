"""Domain-specific error handlers for the YouTube MCP skill."""

from orchid_commons import APIError, ErrorResponse, create_fastapi_error_middleware

from src.application.services.ingestion import IngestionError
from src.domain.exceptions import (
    ChunkNotFoundException,
    DomainException,
    IngestionException,
    InvalidYouTubeUrlException,
    VideoNotFoundException,
    VideoNotReadyException,
)


def _handle_invalid_youtube_url(exc: Exception) -> ErrorResponse:
    return ErrorResponse(code="INVALID_YOUTUBE_URL", message=str(exc), status_code=400)


def _handle_video_not_found(exc: Exception) -> ErrorResponse:
    assert isinstance(exc, VideoNotFoundException)
    return ErrorResponse(
        code="VIDEO_NOT_FOUND",
        message=str(exc),
        status_code=404,
        details={"video_id": exc.video_id},
    )


def _handle_chunk_not_found(exc: Exception) -> ErrorResponse:
    return ErrorResponse(code="CHUNK_NOT_FOUND", message=str(exc), status_code=404)


def _handle_video_not_ready(exc: Exception) -> ErrorResponse:
    return ErrorResponse(code="VIDEO_NOT_READY", message=str(exc), status_code=409)


def _handle_ingestion_error(exc: Exception) -> ErrorResponse:
    assert isinstance(exc, IngestionError)
    from src.application.dtos.ingestion import ProcessingStep

    if exc.step == ProcessingStep.VALIDATING:
        return ErrorResponse(
            code="VALIDATION_ERROR",
            message=str(exc),
            status_code=400,
            details={"step": exc.step.value},
        )
    import logging

    return ErrorResponse(
        code="INGESTION_ERROR",
        message=str(exc),
        status_code=500,
        details={"step": exc.step.value},
        log_level=logging.ERROR,
    )


def _handle_ingestion_exception(exc: Exception) -> ErrorResponse:
    assert isinstance(exc, IngestionException)
    import logging

    return ErrorResponse(
        code="INGESTION_ERROR",
        message=str(exc),
        status_code=500,
        details={"video_id": exc.video_id, "stage": exc.stage},
        log_level=logging.ERROR,
    )


def _handle_domain_exception(exc: Exception) -> ErrorResponse:
    return ErrorResponse(code="DOMAIN_ERROR", message=str(exc), status_code=400)


def build_error_middleware():
    """Create the error-handling middleware with all YouTube domain handlers."""
    handlers = [
        (InvalidYouTubeUrlException, _handle_invalid_youtube_url),
        (VideoNotFoundException, _handle_video_not_found),
        (ChunkNotFoundException, _handle_chunk_not_found),
        (VideoNotReadyException, _handle_video_not_ready),
        (IngestionError, _handle_ingestion_error),
        (IngestionException, _handle_ingestion_exception),
        (DomainException, _handle_domain_exception),
    ]
    return create_fastapi_error_middleware(
        handlers=handlers,
        catch_all_message="An unexpected error occurred",
    )
