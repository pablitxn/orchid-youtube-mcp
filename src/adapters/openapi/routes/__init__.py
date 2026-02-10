"""API route handlers."""

from src.adapters.openapi.routes import health, ingestion, query, sources, videos

__all__ = [
    "health",
    "ingestion",
    "query",
    "sources",
    "videos",
]
