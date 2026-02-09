"""Health check endpoints."""

from collections.abc import Awaitable, Callable
from enum import Enum
from inspect import isawaitable
from typing import Any, cast

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from src.api.dependencies import FactoryDep, SettingsDep

router = APIRouter()


class HealthStatus(str, Enum):
    """Health check status."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth(BaseModel):
    """Health status of a single component."""

    name: str = Field(description="Component name")
    status: HealthStatus = Field(description="Component health status")
    message: str | None = Field(default=None, description="Additional details")


class HealthResponse(BaseModel):
    """Health check response."""

    status: HealthStatus = Field(description="Overall health status")
    version: str = Field(description="Application version")
    environment: str = Field(description="Deployment environment")
    components: list[ComponentHealth] = Field(
        default_factory=list,
        description="Individual component health",
    )


class LivenessResponse(BaseModel):
    """Simple liveness response."""

    status: str = Field(default="ok")


class ReadinessResponse(BaseModel):
    """Readiness check response."""

    ready: bool = Field(description="Whether the service is ready to accept requests")
    checks: dict[str, bool] = Field(
        default_factory=dict,
        description="Individual readiness checks",
    )


async def _run_resource_health_check(resource: Any) -> tuple[bool, str | None]:
    """Execute health check if resource exposes one."""
    health_check = getattr(resource, "health_check", None)
    if not callable(health_check):
        return True, None

    result = health_check()
    if isawaitable(result):
        result = await cast("Awaitable[Any]", result)

    healthy = bool(getattr(result, "healthy", True))
    message = getattr(result, "message", None)
    latency_ms = getattr(result, "latency_ms", None)

    parts: list[str] = []
    if isinstance(message, str) and message:
        parts.append(message)
    if isinstance(latency_ms, int | float):
        parts.append(f"{latency_ms:.1f}ms")

    return healthy, ", ".join(parts) if parts else None


async def _evaluate_component(
    *,
    name: str,
    provider: str,
    getter: Callable[[], Any],
) -> tuple[ComponentHealth, bool]:
    try:
        resource = getter()
    except Exception as exc:
        return (
            ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=str(exc),
            ),
            False,
        )

    try:
        healthy, status_message = await _run_resource_health_check(resource)
    except Exception as exc:
        return (
            ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=str(exc),
            ),
            False,
        )

    message = f"Provider: {provider}"
    if status_message:
        message = f"{message} | {status_message}"

    return (
        ComponentHealth(
            name=name,
            status=HealthStatus.HEALTHY if healthy else HealthStatus.UNHEALTHY,
            message=message,
        ),
        healthy,
    )


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Health check",
    description="Get overall health status of the service and its components.",
)
async def health_check(
    settings: SettingsDep,
    factory: FactoryDep,
) -> HealthResponse:
    """Check health of all service components."""
    checks: dict[str, bool] = {}
    components: list[ComponentHealth] = []

    for component_name, provider_name, getter in [
        ("blob_storage", settings.blob_storage.provider, factory.get_blob_storage),
        ("vector_db", settings.vector_db.provider, factory.get_vector_db),
        ("document_db", settings.document_db.provider, factory.get_document_db),
    ]:
        component_health, healthy = await _evaluate_component(
            name=component_name,
            provider=provider_name,
            getter=getter,
        )
        components.append(component_health)
        checks[component_name] = healthy

    healthy_count = sum(1 for value in checks.values() if value)
    if healthy_count == len(checks):
        overall_status = HealthStatus.HEALTHY
    elif healthy_count == 0:
        overall_status = HealthStatus.UNHEALTHY
    else:
        overall_status = HealthStatus.DEGRADED

    return HealthResponse(
        status=overall_status,
        version=settings.app.version,
        environment=settings.app.environment,
        components=components,
    )


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
    response_model=ReadinessResponse,
    summary="Readiness probe",
    description="Readiness check for Kubernetes probes.",
)
async def readiness(
    factory: FactoryDep,
    response: Response,
) -> ReadinessResponse:
    """Check if service is ready to accept requests.

    Verifies all critical dependencies are available.
    """
    checks: dict[str, bool] = {}

    for component_name, getter in [
        ("blob_storage", factory.get_blob_storage),
        ("vector_db", factory.get_vector_db),
        ("document_db", factory.get_document_db),
    ]:
        try:
            resource = getter()
            healthy, _ = await _run_resource_health_check(resource)
            checks[component_name] = healthy
        except Exception:
            checks[component_name] = False

    # Ready if all critical checks pass
    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return ReadinessResponse(ready=ready, checks=checks)
