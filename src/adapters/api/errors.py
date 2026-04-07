"""Local API error primitives compatible with the current orchid_commons version."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    from starlette.requests import Request
    from starlette.responses import Response


@dataclass(slots=True)
class ErrorResponse:
    """Serializable API error payload returned by middleware handlers."""

    code: str
    message: str
    status_code: int
    details: dict[str, Any] | None = None
    log_level: int = field(default=logging.WARNING)

    def to_payload(self) -> dict[str, Any]:
        """Convert to the JSON payload exposed by the API."""
        payload: dict[str, Any] = {
            "error": {
                "code": self.code,
                "message": self.message,
            }
        }
        if self.details:
            payload["error"]["details"] = self.details
        return payload


class APIError(Exception):
    """Explicit HTTP error raised from routes."""

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details

    def to_error_response(self) -> ErrorResponse:
        """Convert exception to middleware response shape."""
        return ErrorResponse(
            code=self.code,
            message=self.message,
            status_code=self.status_code,
            details=self.details,
        )


def create_fastapi_error_middleware(
    *,
    handlers: list[tuple[type[Exception], Any]],
    catch_all_message: str,
):
    """Create a simple FastAPI middleware for domain/route exceptions."""

    async def middleware(
        request: Request,
        call_next: Any,
    ) -> Response:
        try:
            return await call_next(request)
        except APIError as exc:
            error = exc.to_error_response()
            return JSONResponse(
                status_code=error.status_code,
                content=error.to_payload(),
            )
        except Exception as exc:
            for exc_type, handler in handlers:
                if isinstance(exc, exc_type):
                    error = handler(exc)
                    return JSONResponse(
                        status_code=error.status_code,
                        content=error.to_payload(),
                    )

            error = ErrorResponse(
                code="INTERNAL_SERVER_ERROR",
                message=catch_all_message,
                status_code=500,
            )
            return JSONResponse(
                status_code=error.status_code,
                content=error.to_payload(),
            )

    return middleware
