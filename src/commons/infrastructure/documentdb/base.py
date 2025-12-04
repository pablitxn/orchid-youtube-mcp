"""Abstract base class for document database operations."""

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from src.commons.infrastructure.blob.base import HealthStatus

T = TypeVar("T", bound=dict[str, Any])


class DocumentDBBase(ABC):
    """Abstract base class for document database operations.

    Implementations should handle:
    - MongoDB
    - PostgreSQL with JSONB
    """

    @abstractmethod
    async def insert(
        self,
        collection: str,
        document: dict[str, Any],
    ) -> str:
        """Insert a document.

        Args:
            collection: Collection/table name.
            document: Document to insert.

        Returns:
            Generated document ID.
        """

    @abstractmethod
    async def insert_many(
        self,
        collection: str,
        documents: list[dict[str, Any]],
    ) -> list[str]:
        """Insert multiple documents.

        Args:
            collection: Collection/table name.
            documents: List of documents to insert.

        Returns:
            List of generated document IDs.
        """

    @abstractmethod
    async def find_by_id(
        self,
        collection: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        """Find a document by ID.

        Args:
            collection: Collection/table name.
            document_id: Document ID to find.

        Returns:
            Document if found, None otherwise.
        """

    @abstractmethod
    async def find(
        self,
        collection: str,
        filters: dict[str, Any],
        skip: int = 0,
        limit: int = 100,
        sort: list[tuple[str, int]] | None = None,
    ) -> list[dict[str, Any]]:
        """Find documents matching filters.

        Args:
            collection: Collection/table name.
            filters: Query filters.
            skip: Number of documents to skip.
            limit: Maximum documents to return.
            sort: Sort specification [(field, direction)].
                  Direction: 1 for ascending, -1 for descending.

        Returns:
            List of matching documents.
        """

    @abstractmethod
    async def find_one(
        self,
        collection: str,
        filters: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Find a single document matching filters.

        Args:
            collection: Collection/table name.
            filters: Query filters.

        Returns:
            First matching document or None.
        """

    @abstractmethod
    async def update(
        self,
        collection: str,
        document_id: str,
        updates: dict[str, Any],
    ) -> bool:
        """Update a document.

        Args:
            collection: Collection/table name.
            document_id: Document ID to update.
            updates: Fields to update.

        Returns:
            True if updated, False if not found.
        """

    @abstractmethod
    async def update_many(
        self,
        collection: str,
        filters: dict[str, Any],
        updates: dict[str, Any],
    ) -> int:
        """Update multiple documents.

        Args:
            collection: Collection/table name.
            filters: Query filters.
            updates: Fields to update.

        Returns:
            Count of updated documents.
        """

    @abstractmethod
    async def delete(
        self,
        collection: str,
        document_id: str,
    ) -> bool:
        """Delete a document.

        Args:
            collection: Collection/table name.
            document_id: Document ID to delete.

        Returns:
            True if deleted, False if not found.
        """

    @abstractmethod
    async def delete_many(
        self,
        collection: str,
        filters: dict[str, Any],
    ) -> int:
        """Delete multiple documents.

        Args:
            collection: Collection/table name.
            filters: Query filters.

        Returns:
            Count of deleted documents.
        """

    @abstractmethod
    async def count(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        """Count documents matching filters.

        Args:
            collection: Collection/table name.
            filters: Optional query filters.

        Returns:
            Count of matching documents.
        """

    @abstractmethod
    async def create_index(
        self,
        collection: str,
        fields: list[tuple[str, int]],
        unique: bool = False,
        name: str | None = None,
    ) -> str:
        """Create an index on the collection.

        Args:
            collection: Collection/table name.
            fields: Index fields [(field, direction)].
            unique: Whether index should be unique.
            name: Optional index name.

        Returns:
            Index name.
        """

    @abstractmethod
    async def health_check(self) -> HealthStatus:
        """Check service health.

        Returns:
            Health status with latency info.
        """
