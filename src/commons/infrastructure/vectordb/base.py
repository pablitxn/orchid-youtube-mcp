"""Abstract base class for vector database operations."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from src.commons.infrastructure.blob.base import HealthStatus


@dataclass
class VectorPoint:
    """A vector with its ID and payload."""

    id: str
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class SearchResult:
    """Result from a vector search."""

    id: str
    score: float
    payload: dict[str, Any]


class VectorDBBase(ABC):
    """Abstract base class for vector database operations.

    Implementations should handle:
    - Qdrant
    - Pinecone
    - Weaviate
    - Milvus
    """

    @abstractmethod
    async def create_collection(
        self,
        name: str,
        vector_size: int,
        distance_metric: Literal["cosine", "euclidean", "dot"] = "cosine",
    ) -> bool:
        """Create a new collection/index.

        Args:
            name: Collection name.
            vector_size: Dimension of vectors.
            distance_metric: Similarity metric.

        Returns:
            True if created, False if already exists.
        """

    @abstractmethod
    async def delete_collection(self, name: str) -> bool:
        """Delete a collection.

        Args:
            name: Collection name.

        Returns:
            True if deleted, False if didn't exist.
        """

    @abstractmethod
    async def collection_exists(self, name: str) -> bool:
        """Check if collection exists.

        Args:
            name: Collection name.

        Returns:
            True if exists, False otherwise.
        """

    @abstractmethod
    async def upsert(
        self,
        collection: str,
        points: list[VectorPoint],
    ) -> int:
        """Insert or update vectors.

        Args:
            collection: Collection name.
            points: List of vectors with IDs and payloads.

        Returns:
            Count of upserted points.
        """

    @abstractmethod
    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        """Search for similar vectors.

        Args:
            collection: Collection name.
            query_vector: Query embedding.
            limit: Maximum results to return.
            filters: Optional payload filters.
            score_threshold: Minimum similarity score.

        Returns:
            List of search results sorted by similarity.
        """

    @abstractmethod
    async def delete_by_filter(
        self,
        collection: str,
        filters: dict[str, Any],
    ) -> int:
        """Delete vectors matching filter.

        Args:
            collection: Collection name.
            filters: Payload filters to match.

        Returns:
            Count of deleted vectors.
        """

    @abstractmethod
    async def delete_by_ids(
        self,
        collection: str,
        ids: list[str],
    ) -> int:
        """Delete vectors by their IDs.

        Args:
            collection: Collection name.
            ids: List of vector IDs to delete.

        Returns:
            Count of deleted vectors.
        """

    @abstractmethod
    async def get_by_ids(
        self,
        collection: str,
        ids: list[str],
    ) -> list[VectorPoint]:
        """Retrieve vectors by ID.

        Args:
            collection: Collection name.
            ids: List of vector IDs.

        Returns:
            List of found vectors.
        """

    @abstractmethod
    async def count(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        """Count vectors in collection.

        Args:
            collection: Collection name.
            filters: Optional payload filters.

        Returns:
            Count of matching vectors.
        """

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Check service health.

        Returns:
            Health status with latency info.
        """

    async def ensure_payload_indexes(self, collection: str) -> None:
        """Ensure payload indexes exist for filtering.

        Args:
            collection: Collection name.

        Note:
            Default implementation is a no-op. Override in implementations
            that require explicit index creation (e.g., Qdrant).
        """
        _ = collection  # Default no-op implementation
