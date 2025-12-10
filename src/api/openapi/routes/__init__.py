"""API route handlers."""

from src.api.openapi.routes import health, ingestion, query, videos

__all__ = [
    "health",
    "ingestion",
    "query",
    "videos",
]
