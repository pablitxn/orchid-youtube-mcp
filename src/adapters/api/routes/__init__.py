"""API route handlers."""

from src.adapters.api.routes import (
    admin,
    agent,
    health,
    ingestion,
    query,
    sources,
    videos,
)

__all__ = [
    "admin",
    "agent",
    "health",
    "ingestion",
    "query",
    "sources",
    "videos",
]
