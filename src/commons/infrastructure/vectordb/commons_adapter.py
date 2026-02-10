"""Compatibility adapter over orchid_commons vector store contract."""

from __future__ import annotations

import contextlib
from collections.abc import Mapping, Sequence
from typing import Any, Literal

from orchid_commons.db import VectorPoint as CommonsVectorPoint
from orchid_commons.db import VectorStore

from src.commons.infrastructure.blob.base import HealthStatus
from src.commons.infrastructure.vectordb.base import (
    SearchResult,
    VectorDBBase,
    VectorPoint,
)


def _normalize_dense_vector(raw: Any) -> list[float] | None:
    """Extract dense vector from qdrant point payloads."""
    if raw is None:
        return None

    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        if all(isinstance(value, int | float) for value in raw):
            return [float(value) for value in raw]
        return None

    if isinstance(raw, Mapping):
        for value in raw.values():
            normalized = _normalize_dense_vector(value)
            if normalized is not None:
                return normalized

    return None


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


def _should_use_qdrant_search_fallback(exc: Exception) -> bool:
    message = str(exc).lower()
    return (
        "has no attribute 'search'" in message
        or "object has no attribute search" in message
    )


def _build_qdrant_filter(filters: dict[str, Any], models: Any) -> Any:
    conditions: list[Any] = []

    for field, value in filters.items():
        if isinstance(value, dict):
            for op, op_value in value.items():
                if op == "$gte":
                    conditions.append(
                        models.FieldCondition(
                            key=field,
                            range=models.Range(gte=op_value),
                        )
                    )
                elif op == "$gt":
                    conditions.append(
                        models.FieldCondition(
                            key=field,
                            range=models.Range(gt=op_value),
                        )
                    )
                elif op == "$lte":
                    conditions.append(
                        models.FieldCondition(
                            key=field,
                            range=models.Range(lte=op_value),
                        )
                    )
                elif op == "$lt":
                    conditions.append(
                        models.FieldCondition(
                            key=field,
                            range=models.Range(lt=op_value),
                        )
                    )
                elif op == "$in":
                    conditions.append(
                        models.FieldCondition(
                            key=field,
                            match=models.MatchAny(any=op_value),
                        )
                    )
        else:
            conditions.append(
                models.FieldCondition(
                    key=field,
                    match=models.MatchValue(value=value),
                )
            )

    return models.Filter(must=conditions)


class CommonsVectorStoreAdapter(VectorDBBase):
    """Expose app VectorDB contract over commons ``VectorStore``."""

    def __init__(self, store: VectorStore) -> None:
        self._store = store

    def _client(self) -> Any | None:
        return getattr(self._store, "client", None)

    def _scoped_collection(self, name: str) -> str:
        scoped_collection = getattr(self._store, "scoped_collection", None)
        if callable(scoped_collection):
            return str(scoped_collection(name))
        return name

    async def create_collection(
        self,
        name: str,
        vector_size: int,
        distance_metric: Literal["cosine", "euclidean", "dot"] = "cosine",
    ) -> bool:
        if await self.collection_exists(name):
            return False

        create_collection = getattr(self._store, "create_collection", None)
        if not callable(create_collection):
            raise RuntimeError(
                "Managed vector resource does not support create_collection"
            )

        await create_collection(
            name,
            vector_size=vector_size,
            distance=distance_metric,
        )
        await self.ensure_payload_indexes(name)
        return True

    async def delete_collection(self, name: str) -> bool:
        if not await self.collection_exists(name):
            return False

        client = self._client()
        delete_collection = getattr(client, "delete_collection", None)
        if not callable(delete_collection):
            raise RuntimeError(
                "Managed vector resource does not expose delete_collection"
            )

        await delete_collection(collection_name=self._scoped_collection(name))
        return True

    async def collection_exists(self, name: str) -> bool:
        client = self._client()
        get_collection = getattr(client, "get_collection", None)
        if callable(get_collection):
            try:
                await get_collection(collection_name=self._scoped_collection(name))
                return True
            except Exception:
                return False

        try:
            await self._store.count(name)
            return True
        except Exception:
            return False

    async def upsert(
        self,
        collection: str,
        points: list[VectorPoint],
    ) -> int:
        if not points:
            return 0

        normalized_points = [
            CommonsVectorPoint(
                id=point.id,
                vector=list(point.vector),
                payload=dict(point.payload),
            )
            for point in points
        ]
        return await self._store.upsert(collection, normalized_points)

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        try:
            results = await self._store.search(
                collection,
                query_vector,
                limit=limit,
                filters=filters,
                score_threshold=score_threshold,
                with_payload=True,
                with_vectors=False,
            )
            return [
                SearchResult(
                    id=str(result.id),
                    score=result.score,
                    payload=dict(result.payload),
                )
                for result in results
            ]
        except Exception as exc:
            if not _should_use_qdrant_search_fallback(exc):
                raise
            fallback_exc = exc

        client = self._client()
        query_points = getattr(client, "query_points", None)
        if not callable(query_points):
            raise fallback_exc

        try:
            from qdrant_client import models
        except ImportError:
            raise fallback_exc from None

        query_filter = _build_qdrant_filter(filters, models) if filters else None
        response = await query_points(
            collection_name=self._scoped_collection(collection),
            query=query_vector,
            limit=limit,
            query_filter=query_filter,
            score_threshold=score_threshold,
            with_payload=True,
            with_vectors=False,
        )
        points = getattr(response, "points", [])
        return [
            SearchResult(
                id=str(point.id),
                score=float(point.score or 0.0),
                payload=dict(point.payload or {}),
            )
            for point in points
        ]

    async def delete_by_filter(
        self,
        collection: str,
        filters: dict[str, Any],
    ) -> int:
        return await self._store.delete(collection, filters=filters)

    async def delete_by_ids(
        self,
        collection: str,
        ids: list[str],
    ) -> int:
        if not ids:
            return 0
        return await self._store.delete(collection, ids=ids)

    async def get_by_ids(
        self,
        collection: str,
        ids: list[str],
    ) -> list[VectorPoint]:
        if not ids:
            return []

        client = self._client()
        retrieve = getattr(client, "retrieve", None)
        if not callable(retrieve):
            raise RuntimeError("Managed vector resource does not expose retrieve")

        results = await retrieve(
            collection_name=self._scoped_collection(collection),
            ids=ids,
            with_vectors=True,
        )

        points: list[VectorPoint] = []
        for result in results:
            vector = _normalize_dense_vector(getattr(result, "vector", None))
            if vector is None:
                continue

            point_id = getattr(result, "id", None)
            if point_id is None:
                continue

            payload = getattr(result, "payload", None) or {}
            points.append(
                VectorPoint(
                    id=str(point_id),
                    vector=vector,
                    payload=dict(payload),
                )
            )
        return points

    async def count(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        return await self._store.count(collection, filters=filters)

    async def health_check(self) -> HealthStatus:
        status = await self._store.health_check()
        return _to_local_health(status)

    async def ensure_payload_indexes(self, collection: str) -> None:
        client = self._client()
        create_payload_index = getattr(client, "create_payload_index", None)
        if not callable(create_payload_index):
            return

        with contextlib.suppress(ImportError):
            from qdrant_client import models

            scoped_collection = self._scoped_collection(collection)
            for field in ("video_id", "modality"):
                with contextlib.suppress(Exception):
                    await create_payload_index(
                        collection_name=scoped_collection,
                        field_name=field,
                        field_schema=models.PayloadSchemaType.KEYWORD,
                    )

    async def close(self) -> None:
        await self._store.close()
