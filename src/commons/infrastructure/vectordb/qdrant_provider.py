"""Qdrant implementation of vector database."""

import time
from typing import Any, Literal

from qdrant_client import AsyncQdrantClient, models

from src.commons.infrastructure.blob.base import HealthStatus
from src.commons.infrastructure.vectordb.base import (
    SearchResult,
    VectorDBBase,
    VectorPoint,
)


class QdrantVectorDB(VectorDBBase):
    """Qdrant implementation of vector database.

    Supports both local Qdrant and Qdrant Cloud.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6333,
        grpc_port: int = 6334,
        api_key: str | None = None,
        url: str | None = None,
        prefer_grpc: bool = True,
    ) -> None:
        """Initialize Qdrant client.

        Args:
            host: Qdrant server host.
            port: Qdrant HTTP port.
            grpc_port: Qdrant gRPC port.
            api_key: API key for Qdrant Cloud.
            url: Full URL (overrides host/port, for Qdrant Cloud).
            prefer_grpc: Use gRPC for operations (faster).
        """
        if url:
            self._client = AsyncQdrantClient(
                url=url,
                api_key=api_key,
                prefer_grpc=prefer_grpc,
            )
        else:
            self._client = AsyncQdrantClient(
                host=host,
                port=port,
                grpc_port=grpc_port,
                api_key=api_key,
                prefer_grpc=prefer_grpc,
            )
        self._host = host
        self._port = port

    async def create_collection(
        self,
        name: str,
        vector_size: int,
        distance_metric: Literal["cosine", "euclidean", "dot"] = "cosine",
    ) -> bool:
        """Create a new collection/index."""
        exists = await self.collection_exists(name)
        if exists:
            return False

        distance_map = {
            "cosine": models.Distance.COSINE,
            "euclidean": models.Distance.EUCLID,
            "dot": models.Distance.DOT,
        }

        await self._client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(
                size=vector_size,
                distance=distance_map[distance_metric],
            ),
        )
        # Create payload indexes for efficient filtering
        await self._client.create_payload_index(
            collection_name=name,
            field_name="video_id",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        await self._client.create_payload_index(
            collection_name=name,
            field_name="modality",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
        return True

    async def delete_collection(self, name: str) -> bool:
        """Delete a collection."""
        exists = await self.collection_exists(name)
        if not exists:
            return False

        await self._client.delete_collection(collection_name=name)
        return True

    async def collection_exists(self, name: str) -> bool:
        """Check if collection exists."""
        try:
            await self._client.get_collection(collection_name=name)
            return True
        except Exception:
            return False

    async def ensure_payload_indexes(self, collection: str) -> None:
        """Ensure payload indexes exist for filtering."""
        import contextlib

        for field in ["video_id", "modality"]:
            with contextlib.suppress(Exception):
                await self._client.create_payload_index(
                    collection_name=collection,
                    field_name=field,
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )

    async def upsert(
        self,
        collection: str,
        points: list[VectorPoint],
    ) -> int:
        """Insert or update vectors."""
        if not points:
            return 0

        qdrant_points = [
            models.PointStruct(
                id=point.id,
                vector=point.vector,
                payload=point.payload,
            )
            for point in points
        ]

        await self._client.upsert(
            collection_name=collection,
            points=qdrant_points,
        )
        return len(points)

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        limit: int = 10,
        filters: dict[str, Any] | None = None,
        score_threshold: float | None = None,
    ) -> list[SearchResult]:
        """Search for similar vectors."""
        qdrant_filter = self._build_filter(filters) if filters else None

        response = await self._client.query_points(
            collection_name=collection,
            query=query_vector,
            limit=limit,
            query_filter=qdrant_filter,
            score_threshold=score_threshold,
        )

        return [
            SearchResult(
                id=str(result.id),
                score=result.score or 0.0,
                payload=result.payload or {},
            )
            for result in response.points
        ]

    async def delete_by_filter(
        self,
        collection: str,
        filters: dict[str, Any],
    ) -> int:
        """Delete vectors matching filter."""
        qdrant_filter = self._build_filter(filters)

        count_before = await self.count(collection, filters)

        await self._client.delete(
            collection_name=collection,
            points_selector=models.FilterSelector(filter=qdrant_filter),
        )

        count_after = await self.count(collection, filters)
        return count_before - count_after

    async def delete_by_ids(
        self,
        collection: str,
        ids: list[str],
    ) -> int:
        """Delete vectors by their IDs."""
        if not ids:
            return 0

        await self._client.delete(
            collection_name=collection,
            points_selector=models.PointIdsList(points=ids),
        )
        return len(ids)

    async def get_by_ids(
        self,
        collection: str,
        ids: list[str],
    ) -> list[VectorPoint]:
        """Retrieve vectors by ID."""
        if not ids:
            return []

        results = await self._client.retrieve(
            collection_name=collection,
            ids=ids,
            with_vectors=True,
        )

        points: list[VectorPoint] = []
        for point in results:
            vec = point.vector
            # Handle dense vectors (list of floats)
            if isinstance(vec, list) and len(vec) > 0:
                first_elem = vec[0]
                if isinstance(first_elem, int | float):
                    points.append(
                        VectorPoint(
                            id=str(point.id),
                            vector=list(vec),
                            payload=point.payload or {},
                        )
                    )
        return points

    async def count(
        self,
        collection: str,
        filters: dict[str, Any] | None = None,
    ) -> int:
        """Count vectors in collection."""
        qdrant_filter = self._build_filter(filters) if filters else None

        result = await self._client.count(
            collection_name=collection,
            count_filter=qdrant_filter,
            exact=True,
        )
        return int(result.count)

    async def health_check(self) -> HealthStatus:
        """Check service health."""
        start = time.perf_counter()
        try:
            await self._client.get_collections()
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthStatus(
                healthy=True,
                latency_ms=latency_ms,
                message="Qdrant is healthy",
                details={"host": self._host, "port": str(self._port)},
            )
        except Exception as e:
            latency_ms = (time.perf_counter() - start) * 1000
            return HealthStatus(
                healthy=False,
                latency_ms=latency_ms,
                message=f"Qdrant health check failed: {e}",
                details={"host": self._host, "port": str(self._port), "error": str(e)},
            )

    def _build_filter(self, filters: dict[str, Any]) -> models.Filter:
        """Build Qdrant filter from dict.

        Supports:
        - Simple equality: {"field": "value"}
        - Range: {"field": {"$gte": 10, "$lt": 20}}
        - In list: {"field": {"$in": [1, 2, 3]}}
        """
        conditions: list[models.Condition] = []

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

    async def close(self) -> None:
        """Close the client connection."""
        await self._client.close()
