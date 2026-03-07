"""Smoke tests for MCP SSE route exposure."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from src.adapters.main import create_app


def _make_settings() -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(name="test-app", version="0.1.0", environment="test"),
        server=SimpleNamespace(cors_origins=["*"], api_prefix="/v1", docs_enabled=True),
    )


def _create_test_app(monkeypatch) -> Any:
    monkeypatch.setattr("src.adapters.main.get_settings", lambda: _make_settings())
    monkeypatch.setattr("src.adapters.main.init_services", AsyncMock())
    monkeypatch.setattr("src.adapters.main.shutdown_services", AsyncMock())
    return create_app()


def test_app_registers_mcp_sse_routes(monkeypatch) -> None:
    app = _create_test_app(monkeypatch)

    paths = {route.path for route in app.routes}

    assert "/sse" in paths
    assert "/messages" in paths


def test_messages_endpoint_is_served_by_mcp_transport(monkeypatch) -> None:
    app = _create_test_app(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/messages",
            content="{}",
            headers={"content-type": "application/json"},
        )

    assert response.status_code == 400
    assert response.text == "session_id is required"
