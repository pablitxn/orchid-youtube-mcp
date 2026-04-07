"""API route handlers."""

from src.adapters.api.routes import audio, health, ingestion, query, sources, videos

__all__ = [
    "audio",
    "health",
    "ingestion",
    "query",
    "sources",
    "videos",
]
