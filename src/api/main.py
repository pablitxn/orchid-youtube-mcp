"""FastAPI application factory and lifespan management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.dependencies import get_settings, init_services, shutdown_services
from src.api.middleware.error_handler import error_handler_middleware
from src.api.middleware.logging import LoggingMiddleware
from src.api.openapi.routes import health, ingestion, query, sources, videos


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan - startup and shutdown.

    Initializes all infrastructure services on startup and
    cleanly shuts them down on application exit.
    """
    settings = get_settings()

    # Initialize services
    await init_services(settings)

    yield

    # Cleanup
    await shutdown_services()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    Returns:
        Configured FastAPI application instance.
    """
    settings = get_settings()

    app = FastAPI(
        title=settings.app.name,
        version=settings.app.version,
        description="YouTube RAG Server - MCP tools for video content analysis",
        docs_url="/docs" if settings.server.docs_enabled else None,
        redoc_url="/redoc" if settings.server.docs_enabled else None,
        openapi_url="/openapi.json" if settings.server.docs_enabled else None,
        lifespan=lifespan,
    )

    # Add middleware
    _configure_middleware(app, settings)

    # Register routes
    _register_routes(app, settings)

    return app


def _configure_middleware(app: FastAPI, settings: Any) -> None:
    """Configure application middleware."""
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.server.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Logging middleware
    app.add_middleware(LoggingMiddleware)

    # Error handler (as middleware)
    app.middleware("http")(error_handler_middleware)


def _register_routes(app: FastAPI, settings: Any) -> None:
    """Register API routes."""
    prefix = settings.server.api_prefix

    # Health routes (no prefix for standard health checks)
    app.include_router(health.router, tags=["Health"])

    # API routes with version prefix
    app.include_router(ingestion.router, prefix=prefix, tags=["Ingestion"])
    app.include_router(query.router, prefix=prefix, tags=["Query"])
    app.include_router(sources.router, prefix=prefix, tags=["Sources"])
    app.include_router(videos.router, prefix=prefix, tags=["Videos"])


# Create default app instance
app = create_app()
