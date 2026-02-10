"""Integration tests for commons-backed storage adapters."""

from __future__ import annotations

import asyncio
from time import monotonic
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
import pytest_asyncio
from orchid_commons import create_mongodb_resource, create_qdrant_vector_store
from orchid_commons.config.resources import MongoDbSettings, QdrantSettings

from src.commons.infrastructure.blob import MultiBucketBlobStorageAdapter
from src.commons.infrastructure.documentdb import CommonsMongoDocumentDBAdapter
from src.commons.infrastructure.vectordb import CommonsVectorStoreAdapter, VectorPoint

if TYPE_CHECKING:
    from tests.integration.conftest import IntegrationServiceConfig

pytestmark = pytest.mark.integration


async def _wait_for_count(
    adapter: CommonsVectorStoreAdapter,
    collection: str,
    expected: int,
    *,
    timeout_seconds: float = 5.0,
) -> None:
    deadline = monotonic() + timeout_seconds
    while monotonic() < deadline:
        if await adapter.count(collection) == expected:
            return
        await asyncio.sleep(0.2)
    assert await adapter.count(collection) == expected


@pytest_asyncio.fixture
async def blob_adapter(
    require_integration_services: IntegrationServiceConfig,
) -> MultiBucketBlobStorageAdapter:
    config = require_integration_services
    adapter = MultiBucketBlobStorageAdapter.from_settings(
        endpoint=config.minio_endpoint,
        access_key=config.minio_access_key,
        secret_key=config.minio_secret_key,
        secure=config.minio_secure,
        buckets=dict(config.minio_buckets),
    )
    for bucket_alias in config.minio_buckets:
        await adapter.create_bucket(bucket_alias)
    try:
        yield adapter
    finally:
        await adapter.close()


@pytest_asyncio.fixture
async def mongo_adapter(
    require_integration_services: IntegrationServiceConfig,
) -> CommonsMongoDocumentDBAdapter:
    config = require_integration_services
    mongodb_uri = config.mongodb_uri
    if mongodb_uri is None:
        raise RuntimeError("MongoDB URI was not resolved for integration test")

    resource = await create_mongodb_resource(
        MongoDbSettings(
            uri=mongodb_uri,
            database=config.mongodb_database,
            server_selection_timeout_ms=1500,
            connect_timeout_ms=1500,
            ping_timeout_seconds=1.5,
            app_name="youtube-mcp-integration-tests",
        )
    )
    adapter = CommonsMongoDocumentDBAdapter(resource)
    try:
        yield adapter
    finally:
        await adapter.close()


@pytest_asyncio.fixture
async def vector_adapter(
    require_integration_services: IntegrationServiceConfig,
) -> CommonsVectorStoreAdapter:
    config = require_integration_services
    store = await create_qdrant_vector_store(
        QdrantSettings(
            url=config.qdrant_url,
            host=config.qdrant_host,
            port=config.qdrant_port,
            grpc_port=config.qdrant_grpc_port,
            use_ssl=config.qdrant_use_ssl,
            api_key=config.qdrant_api_key,
            timeout_seconds=5.0,
            prefer_grpc=False,
            collection_prefix=f"ytmcp_it_{uuid4().hex[:8]}",
        )
    )
    adapter = CommonsVectorStoreAdapter(store)
    try:
        yield adapter
    finally:
        await adapter.close()


@pytest.mark.asyncio
async def test_blob_adapter_real_crud_cycle(
    blob_adapter: MultiBucketBlobStorageAdapter,
) -> None:
    key = f"integration/{uuid4().hex}/payload.txt"
    payload = b"orchid commons integration"
    bucket_alias = "videos"

    # Ensure bucket exists first; this is idempotent.
    await blob_adapter.create_bucket(bucket_alias)

    uploaded = await blob_adapter.upload(
        bucket_alias,
        key,
        payload,
        content_type="text/plain",
        metadata={"test-suite": "integration"},
    )
    assert uploaded.path == key
    assert uploaded.size_bytes == len(payload)

    try:
        assert await blob_adapter.exists(bucket_alias, key) is True
        assert await blob_adapter.download(bucket_alias, key) == payload

        listed = await blob_adapter.list_blobs(
            bucket_alias,
            prefix=key.rsplit("/", 1)[0],
            max_results=100,
        )
        assert any(blob.path == key for blob in listed)

        health = await blob_adapter.health_check()
        assert health.healthy is True
    finally:
        assert await blob_adapter.delete(bucket_alias, key) is True
        assert await blob_adapter.exists(bucket_alias, key) is False


@pytest.mark.asyncio
async def test_mongodb_adapter_real_crud_cycle(
    mongo_adapter: CommonsMongoDocumentDBAdapter,
) -> None:
    collection = f"it_docs_{uuid4().hex}"
    document_id = f"doc-{uuid4().hex}"

    inserted = await mongo_adapter.insert(
        collection,
        {
            "id": document_id,
            "title": "integration",
            "status": "pending",
            "views": 10,
        },
    )
    assert inserted == document_id

    try:
        found = await mongo_adapter.find_by_id(collection, document_id)
        assert found is not None
        assert found["id"] == document_id
        assert found["status"] == "pending"

        assert await mongo_adapter.update(
            collection,
            document_id,
            {"status": "ready"},
        )

        found_one = await mongo_adapter.find_one(collection, {"status": "ready"})
        assert found_one is not None
        assert found_one["id"] == document_id

        assert await mongo_adapter.count(collection, {"status": "ready"}) == 1

        updated_many = await mongo_adapter.update_many(
            collection,
            {"status": "ready"},
            {"views": 20},
        )
        assert updated_many == 1

        assert await mongo_adapter.delete(collection, document_id) is True
        assert await mongo_adapter.find_by_id(collection, document_id) is None

        health = await mongo_adapter.health_check()
        assert health.healthy is True
    finally:
        await mongo_adapter.delete_many(collection, {})


@pytest.mark.asyncio
async def test_qdrant_adapter_real_search_and_delete_cycle(
    vector_adapter: CommonsVectorStoreAdapter,
) -> None:
    collection = f"it_vectors_{uuid4().hex}"
    first_id = str(uuid4())
    second_id = str(uuid4())

    assert (
        await vector_adapter.create_collection(
            collection,
            vector_size=4,
            distance_metric="cosine",
        )
        is True
    )

    try:
        upserted = await vector_adapter.upsert(
            collection,
            [
                VectorPoint(
                    id=first_id,
                    vector=[0.1, 0.2, 0.3, 0.4],
                    payload={"video_id": "video-it", "modality": "transcript"},
                ),
                VectorPoint(
                    id=second_id,
                    vector=[-0.1, -0.2, -0.3, -0.4],
                    payload={"video_id": "video-it", "modality": "frame"},
                ),
            ],
        )
        assert upserted == 2
        await _wait_for_count(vector_adapter, collection, 2)

        search_results = await vector_adapter.search(
            collection,
            query_vector=[0.1, 0.2, 0.3, 0.4],
            limit=5,
            filters={"video_id": "video-it"},
        )
        assert len(search_results) >= 1
        assert any(result.id == first_id for result in search_results)

        retrieved = await vector_adapter.get_by_ids(collection, [first_id, second_id])
        retrieved_ids = {point.id for point in retrieved}
        assert {first_id, second_id}.issubset(retrieved_ids)

        assert await vector_adapter.delete_by_ids(collection, [second_id]) == 1
        await _wait_for_count(vector_adapter, collection, 1)

        deleted_by_filter = await vector_adapter.delete_by_filter(
            collection,
            {"video_id": "video-it"},
        )
        assert deleted_by_filter >= 1
        await _wait_for_count(vector_adapter, collection, 0)

        health = await vector_adapter.health_check()
        assert health.healthy is True
    finally:
        await vector_adapter.delete_collection(collection)
