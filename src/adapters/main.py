"""FastAPI application factory and lifespan management."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from mcp.server.sse import SseServerTransport
from orchid_commons import create_fastapi_observability_middleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import Receive, Scope, Send

from src.adapters.api.routes import health, ingestion, query, sources, videos
from src.adapters.dependencies import get_settings, init_services, shutdown_services
from src.adapters.mcp.server import create_mcp_server
from src.adapters.middleware.error_handler import build_error_middleware


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application lifespan - startup and shutdown.

    Initializes all infrastructure services on startup and
    cleanly shuts them down on application exit.
    """
    settings = get_settings()

    # Initialize services
    await init_services(settings, configure_uvicorn_logging=True)

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
        openapi_url="/api.json" if settings.server.docs_enabled else None,
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

    # Correlation IDs and request spans
    app.middleware("http")(create_fastapi_observability_middleware())

    # Error handler (as middleware)
    app.middleware("http")(build_error_middleware())


def _register_routes(app: FastAPI, settings: Any) -> None:
    """Register API routes."""
    prefix = settings.server.api_prefix

    _register_mcp_routes(app)

    # Health routes (no prefix for standard health checks)
    app.include_router(health.router, tags=["Health"])

    # API routes with version prefix
    app.include_router(ingestion.router, prefix=prefix, tags=["Ingestion"])
    app.include_router(query.router, prefix=prefix, tags=["Query"])
    app.include_router(sources.router, prefix=prefix, tags=["Sources"])
    app.include_router(videos.router, prefix=prefix, tags=["Videos"])


def _register_mcp_routes(app: FastAPI) -> None:
    """Expose the MCP server over SSE on the same FastAPI app."""
    mcp_server = create_mcp_server()
    sse_transport = SseServerTransport("/messages")

    async def handle_sse(scope: Scope, receive: Receive, send: Send) -> Response:
        async with sse_transport.connect_sse(scope, receive, send) as streams:
            await mcp_server.run(
                streams[0],
                streams[1],
                mcp_server.create_initialization_options(),
            )
        return Response()

    async def sse_endpoint(request: Request) -> Response:
        return await handle_sse(
            request.scope,
            request.receive,
            request._send,
        )

    app.add_api_route("/sse", sse_endpoint, methods=["GET"], include_in_schema=False)
    app.mount("/messages", sse_transport.handle_post_message, name="mcp-messages")


# Create default app instance
app = create_app()
