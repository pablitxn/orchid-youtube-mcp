"""FastAPI application factory and lifespan management."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.dependencies import get_settings, init_services, shutdown_services
from src.api.middleware.error_handler import error_handler_middleware
from src.api.middleware.logging import LoggingMiddleware
from src.api.openapi.routes import health, ingestion, query, sources, videos
from src.commons.telemetry import configure_logging


def _get_formatter(log_format: str) -> logging.Formatter:
    """Get the appropriate formatter based on format type."""
    from src.commons.telemetry.logger import JsonFormatter, TextFormatter

    if log_format == "json":
        return JsonFormatter()
    return TextFormatter()


def _setup_logging() -> None:
    """Configure logging for the application.

    This must be called at module level to ensure our formatters
    are applied before uvicorn starts.
    """
    settings = get_settings()
    log_level = settings.telemetry.log_level or settings.app.log_level
    log_format = settings.telemetry.log_format

    # Configure root logger for our application
    configure_logging(
        level=log_level,
        format_type=log_format,
        logger_name="src",
    )

    # Also configure root logger as fallback
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper()))


def _configure_uvicorn_logging() -> None:
    """Configure uvicorn loggers to use our format.

    Called during lifespan when uvicorn handlers are available.
    """
    settings = get_settings()
    log_level = settings.telemetry.log_level or settings.app.log_level
    log_format = settings.telemetry.log_format
    formatter = _get_formatter(log_format)

    # Configure uvicorn loggers to use our format for consistency
    uvicorn_loggers = ["uvicorn", "uvicorn.error", "uvicorn.access"]
    for logger_name in uvicorn_loggers:
        logger = logging.getLogger(logger_name)
        logger.setLevel(getattr(logging, log_level.upper()))
        # Replace formatter on existing handlers
        for handler in logger.handlers:
            handler.setFormatter(formatter)
            handler.setLevel(getattr(logging, log_level.upper()))
        # If no handlers yet, add one
        if not logger.handlers:
            import sys

            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(formatter)
            handler.setLevel(getattr(logging, log_level.upper()))
            logger.addHandler(handler)
            logger.propagate = False


# Configure logging at module import time
_setup_logging()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan - startup and shutdown.

    Initializes all infrastructure services on startup and
    cleanly shuts them down on application exit.
    """
    # Configure uvicorn logging now that handlers exist
    _configure_uvicorn_logging()

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
