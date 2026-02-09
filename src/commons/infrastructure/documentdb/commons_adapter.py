"""Compatibility adapter over orchid_commons MongoDB resource contract."""

from __future__ import annotations

from typing import Any

from bson import ObjectId

from src.commons.infrastructure.blob.base import HealthStatus
from src.commons.infrastructure.documentdb.base import DocumentDBBase


def _to_local_health(status: Any) -> HealthStatus:
    details = None
    if status.details is not None:
        details = {key: str(value) for key, value in status.details.items()}

    return HealthStatus(
        healthy=status.healthy,
        latency_ms=status.latency_ms,
        message=status.message,
        details=details,
    )


class CommonsMongoDocumentDBAdapter(DocumentDBBase):
    """Expose app DocumentDB contract over commons MongoDB resource."""

    def __init__(self, resource: Any) -> None:
        self._resource = resource

    def _collection(self, name: str) -> Any:
        collection_factory = getattr(self._resource, "collection", None)
        if not callable(collection_factory):
            raise RuntimeError(
                "Managed document resource does not expose collection access"
            )
        return collection_factory(name)

    @staticmethod
    def _to_storage_document(document: dict[str, Any]) -> dict[str, Any]:
        doc = document.copy()
        if "id" in doc:
            doc["_id"] = doc.pop("id")
        return doc

    @staticmethod
    def _to_domain_document(document: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(document)
        if "_id" in normalized:
            normalized["id"] = str(normalized.pop("_id"))
        return normalized

    async def insert(
        self,
        collection: str,
        document: dict[str, Any],
    ) -> str:
        inserted_id = await self._resource.insert_one(
            collection,
            self._to_storage_document(document),
        )
        return str(inserted_id)

    async def insert_many(
        self,
        collection: str,
        documents: list[dict[str, Any]],
    ) -> list[str]:
        if not documents:
            return []

        transformed = [self._to_storage_document(document) for document in documents]
        result = await self._collection(collection).insert_many(transformed)
        return [str(inserted_id) for inserted_id in result.inserted_ids]

    async def find_by_id(
        self,
        collection: str,
        document_id: str,
    ) -> dict[str, Any] | None:
        document = await self._resource.find_one(collection, {"_id": document_id})
        if document is None:
            try:
                object_id = ObjectId(document_id)
            except Exception:
                return None
            document = await self._resource.find_one(collection, {"_id": object_id})

        if document is None:
            return None
        return self._to_domain_document(document)

    async def find(
        self,
        collection: str,
        filters: dict[str, Any],
        skip: int = 0,
        limit: int = 100,
        sort: list[tuple[str, int]] | None = None,
    ) -> list[dict[str, Any]]:
        cursor = self._collection(collection).find(filters)
        if sort:
            cursor = cursor.sort(sort)
        cursor = cursor.skip(skip).limit(limit)
        documents = await cursor.to_list(length=limit)
        return [self._to_domain_document(document) for document in documents]

    async def find_one(
        self,
        collection: str,
        filters: dict[str, Any],
    ) -> dict[str, Any] | None:
        document = await self._resource.find_one(collection, filters)
        if document is None:
            return None
        return self._to_domain_document(document)

    async def update(
        self,
        collection: str,
        document_id: str,
        updates: dict[str, Any],
    ) -> bool:
        update_doc = updates.copy()
        if "id" in update_doc:
            update_doc["_id"] = update_doc.pop("id")

        if await self._apply_single_update(
            collection=collection,
            query={"_id": document_id},
            update_doc=update_doc,
        ):
            return True

        try:
            object_id = ObjectId(document_id)
        except Exception:
            return False

        return await self._apply_single_update(
            collection=collection,
            query={"_id": object_id},
            update_doc=update_doc,
        )

    async def _apply_single_update(
        self,
        *,
        collection: str,
        query: dict[str, Any],
        update_doc: dict[str, Any],
    ) -> bool:
        existing = await self._resource.find_one(collection, query)
        if existing is None:
            return False

        await self._resource.update_one(
            collection,
            query,
            {"$set": update_doc},
            upsert=False,
        )
        return True

    async def update_many(
        self,
        collection: str,
        filters: dict[str, Any],
        updates: dict[str, Any],
    ) -> int:
        result = await self._collection(collection).update_many(
            filters,
            {"$set": updates},
        )
        return int(result.modified_count)

    async def delete(
        self,
        collection: str,
        document_id: str,
    ) -> bool:
        deleted = await self._resource.delete_one(collection, {"_id": document_id})
        if deleted > 0:
            return True

        try:
            object_id = ObjectId(document_id)
        except Exception:
            return False

        deleted = await self._resource.delete_one(collection, {"_id": object_id})
        return deleted > 0

    async def delete_many(
        self,
        collection: str,
        filters: dict[str, Any],
    ) -> int:
        result = await self._collection(collection).delete_many(filters)
        return int(result.deleted_count)

    async def count(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        return await self._resource.count(collection, filters or {})

    async def create_index(
        self,
        collection: str,
        fields: list[tuple[str, int]],
        unique: bool = False,
        name: str | None = None,
    ) -> str:
        index_name = await self._collection(collection).create_index(
            fields,
            unique=unique,
            name=name,
        )
        return str(index_name)

    async def health_check(self) -> HealthStatus:
        status = await self._resource.health_check()
        return _to_local_health(status)

    async def close(self) -> None:
        await self._resource.close()
