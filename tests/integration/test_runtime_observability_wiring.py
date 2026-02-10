"""Integration tests for runtime startup/factory wiring and observability bootstrap."""

from __future__ import annotations

from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
from orchid_commons import (
    OpenTelemetryMetricsRecorder,
    get_metrics_recorder,
    get_observability_handle,
)

from src.adapters.main import create_app
from src.infrastructure import observability
from src.infrastructure.adapters.blob import BlobStorageAdapter
from src.infrastructure.adapters.document import DocumentStoreAdapter
from src.infrastructure.adapters.vector import VectorStoreAdapter
from src.infrastructure.factory import get_factory
from src.infrastructure.runtime import get_runtime_manager

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_lifespan_wires_runtime_factory_and_observability(
    integration_shared_app_settings,
) -> None:
    request_id = f"it-{uuid4().hex}"
    app = create_app()

    with patch(
        "src.infrastructure.runtime.load_shared_app_settings",
        return_value=integration_shared_app_settings,
    ):
        async with app.router.lifespan_context(app):
            manager = get_runtime_manager()
            assert manager is not None
            assert manager.has("multi_bucket")
            assert manager.has("mongodb")
            assert manager.has("qdrant")

            factory = get_factory()
            assert isinstance(factory.get_blob_storage(), BlobStorageAdapter)
            assert isinstance(factory.get_document_db(), DocumentStoreAdapter)
            assert isinstance(factory.get_vector_db(), VectorStoreAdapter)

            state = observability._StateHolder.state
            assert state is not None
            assert state.logging_bootstrapped is True
            assert state.observability_bootstrapped is True

            handle = get_observability_handle()
            assert handle is not None
            assert handle.enabled is True
            assert handle.tracer_provider is not None

            recorder = get_metrics_recorder()
            assert isinstance(recorder, OpenTelemetryMetricsRecorder)

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://integration.local",
            ) as client:
                forwarded = await client.get(
                    "/health/live",
                    headers={"x-request-id": request_id},
                )
                assert forwarded.status_code == 200
                assert forwarded.headers["x-request-id"] == request_id

                generated = await client.get("/health/live")
                assert generated.status_code == 200
                generated_request_id = generated.headers.get("x-request-id")
                assert generated_request_id is not None
                assert len(generated_request_id) == 32
                int(generated_request_id, 16)

    assert get_runtime_manager() is None
    assert observability._StateHolder.state is None
