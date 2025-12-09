"""Embedding services."""

from src.infrastructure.embeddings.base import (
    EmbeddingModality,
    EmbeddingResult,
    EmbeddingServiceBase,
)
from src.infrastructure.embeddings.clip_embeddings import CLIPEmbeddingService
from src.infrastructure.embeddings.openai_embeddings import OpenAIEmbeddingService

__all__ = [
    # Base classes
    "EmbeddingServiceBase",
    "EmbeddingResult",
    "EmbeddingModality",
    # Implementations
    "OpenAIEmbeddingService",
    "CLIPEmbeddingService",
]
