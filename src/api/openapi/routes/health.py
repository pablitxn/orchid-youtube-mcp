"""Health and readiness endpoints backed by runtime ResourceManager checks."""

from __future__ import annotations

from typing import Any, Literal, cast

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from src.commons.runtime import get_runtime_manager

router = APIRouter()


class HealthCheckStatus(BaseModel):
    """Per-check payload produced by commons health report."""

    healthy: bool = Field(description="Whether the dependency is healthy")
    latency_ms: float = Field(description="Latency for this health check")
    message: str | None = Field(default=None, description="Optional check message")
    details: dict[str, str] | None = Field(
        default=None,
        description="Optional details such as provider or error_type",
    )


class HealthSummary(BaseModel):
    """Aggregated counters for health checks."""

    total: int = Field(description="Total number of checks")
    healthy: int = Field(description="Count of healthy checks")
    unhealthy: int = Field(description="Count of unhealthy checks")


class LivenessResponse(BaseModel):
    """Simple liveness response."""

    status: str = Field(default="ok")


class RuntimeHealthPayload(BaseModel):
    """Runtime health payload aligned with orchid_commons.HealthReport.to_dict()."""

    status: Literal["ok", "degraded", "down"] = Field(
        description="Aggregated status across all runtime checks"
    )
    healthy: bool = Field(description="Legacy alias for readiness")
    readiness: bool = Field(description="Whether required checks are ready")
    liveness: bool = Field(description="Whether process is alive")
    latency_ms: float = Field(description="Total health check execution latency")
    summary: HealthSummary = Field(description="Aggregated check counts")
    checks: dict[str, HealthCheckStatus] = Field(
        default_factory=dict,
        description="Per-resource check payloads",
    )


def _unavailable_manager_payload(
    message: str,
    *,
    details: dict[str, str] | None = None,
) -> dict[str, Any]:
    check_payload: dict[str, Any] = {
        "healthy": False,
        "latency_ms": 0.0,
        "message": message,
    }
    if details:
        check_payload["details"] = details

    checks = {"runtime_manager": check_payload}
    return {
        "status": "down",
        "healthy": False,
        "readiness": False,
        "liveness": True,
        "latency_ms": 0.0,
        "summary": {"total": len(checks), "healthy": 0, "unhealthy": len(checks)},
        "checks": checks,
    }


async def _runtime_health_payload(*, include_optional_checks: bool) -> dict[str, Any]:
    manager = get_runtime_manager()
    if manager is None:
        return _unavailable_manager_payload(
            "Runtime resource manager is not initialized"
        )

    try:
        payload = await manager.health_payload(
            include_optional_checks=include_optional_checks
        )
        if not isinstance(payload, dict):
            return _unavailable_manager_payload(
                "Runtime health payload has invalid type",
                details={"error_type": type(payload).__name__},
            )
        return cast("dict[str, Any]", payload)
    except Exception as exc:
        return _unavailable_manager_payload(
            "Runtime health evaluation failed",
            details={"error_type": type(exc).__name__},
        )


@router.get(
    "/health",
    response_model=RuntimeHealthPayload,
    response_model_exclude_none=True,
    summary="Health check",
    description=(
        "Aggregated runtime health across managed resources "
        "and optional observability backends."
    ),
)
async def health_check() -> dict[str, Any]:
    """Return runtime health payload."""
    return await _runtime_health_payload(include_optional_checks=True)


@router.get(
    "/health/live",
    response_model=LivenessResponse,
    summary="Liveness probe",
    description="Simple liveness check for Kubernetes probes.",
)
async def liveness() -> LivenessResponse:
    """Simple liveness check - just verifies the app is running."""
    return LivenessResponse(status="ok")


@router.get(
    "/health/ready",
    response_model=RuntimeHealthPayload,
    response_model_exclude_none=True,
    summary="Readiness probe",
    description="Readiness probe backed by required runtime resources.",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "description": "Service not ready",
            "model": RuntimeHealthPayload,
        }
    },
)
async def readiness() -> JSONResponse:
    """Return readiness payload and HTTP 503 when runtime is not ready."""
    payload = await _runtime_health_payload(include_optional_checks=False)
    status_code = (
        status.HTTP_200_OK
        if payload.get("readiness", False)
        else status.HTTP_503_SERVICE_UNAVAILABLE
    )
    return JSONResponse(status_code=status_code, content=payload)
