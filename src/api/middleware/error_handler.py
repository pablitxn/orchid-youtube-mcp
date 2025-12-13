"""Error handling middleware and exception handlers."""

from typing import Any

from fastapi import Request, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from src.application.services.ingestion import IngestionError
from src.commons.telemetry.logger import get_logger
from src.domain.exceptions import (
    ChunkNotFoundException,
    DomainException,
    IngestionException,
    InvalidYouTubeUrlException,
    VideoNotFoundException,
    VideoNotReadyException,
)

logger = get_logger(__name__)


class APIError(Exception):
    """Base API error with code and details."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize API error.

        Args:
            code: Error code for clients.
            message: Human-readable error message.
            status_code: HTTP status code.
            details: Additional error details.
        """
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


def _build_error_response(
    request: Request,
    code: str,
    message: str,
    status_code: int,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    """Build standardized error response.

    Args:
        request: HTTP request.
        code: Error code.
        message: Error message.
        status_code: HTTP status code.
        details: Additional details.

    Returns:
        JSON error response.
    """
    request_id = getattr(request.state, "request_id", "unknown")

    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "request_id": request_id,
            }
        },
    )


def _handle_exception(  # noqa: PLR0911
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Handle exception and return appropriate error response.

    Args:
        request: HTTP request.
        exc: Exception to handle.

    Returns:
        JSON error response.
    """
    if isinstance(exc, APIError):
        logger.warning(
            f"API error: {exc.code}",
            extra={
                "error_code": exc.code,
                "error_message": exc.message,
                "details": exc.details,
            },
        )
        return _build_error_response(
            request=request,
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            details=exc.details,
        )

    if isinstance(exc, InvalidYouTubeUrlException):
        logger.warning(f"Invalid video URL: {exc}")
        return _build_error_response(
            request=request,
            code="INVALID_YOUTUBE_URL",
            message=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, VideoNotFoundException):
        logger.warning(f"Video not found: {exc}")
        return _build_error_response(
            request=request,
            code="VIDEO_NOT_FOUND",
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
            details={"video_id": exc.video_id},
        )

    if isinstance(exc, ChunkNotFoundException):
        logger.warning(f"Chunk not found: {exc}")
        return _build_error_response(
            request=request,
            code="CHUNK_NOT_FOUND",
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    if isinstance(exc, VideoNotReadyException):
        logger.warning(f"Video not ready: {exc}")
        return _build_error_response(
            request=request,
            code="VIDEO_NOT_READY",
            message=str(exc),
            status_code=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, IngestionError):
        from src.application.dtos.ingestion import ProcessingStep

        # Validation errors should return 400, other ingestion errors return 500
        if exc.step == ProcessingStep.VALIDATING:
            logger.warning(f"Validation error: {exc}")
            return _build_error_response(
                request=request,
                code="VALIDATION_ERROR",
                message=str(exc),
                status_code=status.HTTP_400_BAD_REQUEST,
                details={"step": exc.step.value},
            )
        logger.error(f"Ingestion error at step {exc.step}: {exc}")
        return _build_error_response(
            request=request,
            code="INGESTION_ERROR",
            message=str(exc),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"step": exc.step.value},
        )

    if isinstance(exc, IngestionException):
        logger.error(f"Ingestion exception at {exc.stage}: {exc}")
        return _build_error_response(
            request=request,
            code="INGESTION_ERROR",
            message=str(exc),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            details={"video_id": exc.video_id, "stage": exc.stage},
        )

    if isinstance(exc, DomainException):
        logger.warning(f"Domain error: {exc}")
        return _build_error_response(
            request=request,
            code="DOMAIN_ERROR",
            message=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    # Catch-all for unexpected errors
    logger.exception(f"Unexpected error: {exc}")
    return _build_error_response(
        request=request,
        code="INTERNAL_ERROR",
        message="An unexpected error occurred",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


async def error_handler_middleware(
    request: Request,
    call_next: RequestResponseEndpoint,
) -> Response:
    """Middleware to catch and format all exceptions.

    Args:
        request: HTTP request.
        call_next: Next handler in chain.

    Returns:
        HTTP response.
    """
    try:
        return await call_next(request)
    except Exception as exc:
        return _handle_exception(request, exc)
