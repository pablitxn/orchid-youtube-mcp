"""MongoDB implementation of document database."""

import time
from typing import Any

from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from src.commons.infrastructure.blob.base import HealthStatus
from src.commons.infrastructure.documentdb.base import DocumentDBBase


class MongoDBDocumentDB(DocumentDBBase):
    """MongoDB implementation of document database.

    Uses Motor for async operations.
    """

    def __init__(
        self,
        connection_string: str,
        database_name: str,
    ) -> None:
        """Initialize MongoDB client.

        Args:
            connection_string: MongoDB connection URI.
            database_name: Name of the database to use.
        """
        self._client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(
            connection_string
        )
        self._db: AsyncIOMotorDatabase[dict[str, Any]] = self._client[database_name]
        self._database_name = database_name

    async def insert(
        self,
        collection: str,
        document: dict[str, Any],
    ) -> str:
        """Insert a document.

        If the document has an 'id' field, it will be used as MongoDB's '_id'.
        This ensures consistency between the domain model ID and MongoDB's ID.
        """
        doc = document.copy()
        # Use the domain model 'id' as MongoDB's '_id' if present
        if "id" in doc:
            doc["_id"] = doc.pop("id")

        result = await self._db[collection].insert_one(doc)
        return str(result.inserted_id)

    async def insert_many(
        self,
        collection: str,
        documents: list[dict[str, Any]],
    ) -> list[str]:
        """Insert multiple documents.

        If documents have an 'id' field, it will be used as MongoDB's '_id'.
        """
        if not documents:
            return []

        docs = []
        for document in documents:
            doc = document.copy()
            if "id" in doc:
                doc["_id"] = doc.pop("id")
            docs.append(doc)

        result = await self._db[collection].insert_many(docs)
        return [str(id_) for id_ in result.inserted_ids]

    async def find_by_id(
        self,
        collection: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        """Find a document by ID.

        Searches by _id field which stores the domain model's 'id'.
        Returns the document with 'id' field restored.
        """
        # First try to find by string _id (our UUID format)
        doc = await self._db[collection].find_one({"_id": document_id})

        # Fallback to ObjectId for backwards compatibility
        if doc is None:
            try:
                obj_id = ObjectId(document_id)
                doc = await self._db[collection].find_one({"_id": obj_id})
            except Exception:
                pass

        if doc:
            # Restore 'id' field from '_id' for domain model compatibility
            doc["id"] = str(doc.pop("_id"))
            return dict(doc)
        return None

    async def find(
        self,
        collection: str,
        filters: dict[str, Any],
        skip: int = 0,
        limit: int = 100,
        sort: list[tuple[str, int]] | None = None,
    ) -> list[dict[str, Any]]:
        """Find documents matching filters.

        Returns documents with 'id' field restored from '_id'.
        """
        cursor = self._db[collection].find(filters)

        if sort:
            cursor = cursor.sort(sort)

        cursor = cursor.skip(skip).limit(limit)

        results: list[dict[str, Any]] = []
        async for doc in cursor:
            # Restore 'id' field from '_id' for domain model compatibility
            doc["id"] = str(doc.pop("_id"))
            results.append(doc)

        return results

    async def find_one(
        self,
        collection: str,
        filters: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Find a single document matching filters.

        Returns the document with 'id' field restored from '_id'.
        """
        doc = await self._db[collection].find_one(filters)
        if doc:
            # Restore 'id' field from '_id' for domain model compatibility
            doc["id"] = str(doc.pop("_id"))
            return dict(doc)
        return None

    async def update(
        self,
        collection: str,
        document_id: str,
        updates: dict[str, Any],
    ) -> bool:
        """Update a document.

        Searches by _id field which stores the domain model's 'id'.
        If updates contain 'id', it will be converted to '_id'.
        """
        # Convert 'id' to '_id' in updates if present
        update_doc = updates.copy()
        if "id" in update_doc:
            update_doc["_id"] = update_doc.pop("id")

        # First try to find by string _id (our UUID format)
        result = await self._db[collection].update_one(
            {"_id": document_id},
            {"$set": update_doc},
        )

        if result.matched_count > 0:
            return bool(result.modified_count > 0 or result.matched_count > 0)

        # Fallback to ObjectId for backwards compatibility
        try:
            obj_id = ObjectId(document_id)
            result = await self._db[collection].update_one(
                {"_id": obj_id},
                {"$set": update_doc},
            )
            return bool(result.modified_count > 0 or result.matched_count > 0)
        except Exception:
            return False

    async def update_many(
        self,
        collection: str,
        filters: dict[str, Any],
        updates: dict[str, Any],
    ) -> int:
        """Update multiple documents."""
        result = await self._db[collection].update_many(
            filters,
            {"$set": updates},
        )
        return int(result.modified_count)

    async def delete(
        self,
        collection: str,
        document_id: str,
    ) -> bool:
        """Delete a document.

        Searches by _id field which stores the domain model's 'id'.
        """
        # First try to delete by string _id (our UUID format)
        result = await self._db[collection].delete_one({"_id": document_id})

        if result.deleted_count > 0:
            return True

        # Fallback to ObjectId for backwards compatibility
        try:
            obj_id = ObjectId(document_id)
            result = await self._db[collection].delete_one({"_id": obj_id})
            return bool(result.deleted_count > 0)
        except Exception:
            return False

    async def delete_many(
        self,
        collection: str,
        filters: dict[str, Any],
    ) -> int:
        """Delete multiple documents."""
        result = await self._db[collection].delete_many(filters)
        return int(result.deleted_count)

    async def count(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        """Count documents matching filters."""
        if filters:
            count = await self._db[collection].count_documents(filters)
            return int(count)
        count = await self._db[collection].estimated_document_count()
        return int(count)

    async def create_index(
        self,
        collection: str,
        fields: list[tuple[str, int]],
        unique: bool = False,
        name: str | None = None,
    ) -> str:
        """Create an index on the collection."""
        index_name = await self._db[collection].create_index(
            fields,
            unique=unique,
            name=name,
        )
        return str(index_name)

    async def health_check(self) -> HealthStatus:
        """Check service health."""
        start = time.perf_counter()
        try:
            await self._client.admin.command("ping")
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthStatus(
                healthy=True,
                latency_ms=latency_ms,
                message="MongoDB is healthy",
                details={"database": self._database_name},
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthStatus(
                healthy=False,
                latency_ms=latency_ms,
                message=f"MongoDB health check failed: {e}",
                details={"database": self._database_name, "error": str(e)},
            )

    async def close(self) -> None:
        """Close the client connection."""
        self._client.close()
