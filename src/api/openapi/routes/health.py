"""Health check endpoints."""

from enum import Enum

from fastapi import APIRouter
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
    components: list[ComponentHealth] = []
    overall_status = HealthStatus.HEALTHY

    # Check blob storage
    try:
        factory.get_blob_storage()
        components.append(
            ComponentHealth(
                name="blob_storage",
                status=HealthStatus.HEALTHY,
                message=f"Provider: {settings.blob_storage.provider}",
            )
        )
    except Exception as e:
        components.append(
            ComponentHealth(
                name="blob_storage",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )
        )
        overall_status = HealthStatus.DEGRADED

    # Check vector database
    try:
        factory.get_vector_db()
        components.append(
            ComponentHealth(
                name="vector_db",
                status=HealthStatus.HEALTHY,
                message=f"Provider: {settings.vector_db.provider}",
            )
        )
    except Exception as e:
        components.append(
            ComponentHealth(
                name="vector_db",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )
        )
        overall_status = HealthStatus.DEGRADED

    # Check document database
    try:
        factory.get_document_db()
        components.append(
            ComponentHealth(
                name="document_db",
                status=HealthStatus.HEALTHY,
                message=f"Provider: {settings.document_db.provider}",
            )
        )
    except Exception as e:
        components.append(
            ComponentHealth(
                name="document_db",
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )
        )
        overall_status = HealthStatus.DEGRADED

    # If any critical component is unhealthy, mark overall as unhealthy
    unhealthy_count = sum(1 for c in components if c.status == HealthStatus.UNHEALTHY)
    if unhealthy_count >= 2:
        overall_status = HealthStatus.UNHEALTHY

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
) -> ReadinessResponse:
    """Check if service is ready to accept requests.

    Verifies all critical dependencies are available.
    """
    checks: dict[str, bool] = {}

    # Check blob storage connectivity
    try:
        factory.get_blob_storage()
        checks["blob_storage"] = True
    except Exception:
        checks["blob_storage"] = False

    # Check vector database connectivity
    try:
        factory.get_vector_db()
        checks["vector_db"] = True
    except Exception:
        checks["vector_db"] = False

    # Check document database connectivity
    try:
        factory.get_document_db()
        checks["document_db"] = True
    except Exception:
        checks["document_db"] = False

    # Ready if all critical checks pass
    ready = all(checks.values())

    return ReadinessResponse(ready=ready, checks=checks)
