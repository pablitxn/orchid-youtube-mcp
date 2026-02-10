"""Contract tests for runtime-backed health and readiness payloads."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Literal
from unittest.mock import AsyncMock

from fastapi import status
from fastapi.testclient import TestClient

from src.adapters.main import create_app


def _make_settings() -> Any:
    return SimpleNamespace(
        app=SimpleNamespace(name="test-app", version="0.1.0", environment="test"),
        server=SimpleNamespace(cors_origins=["*"], api_prefix="/v1", docs_enabled=True),
    )


def _make_payload(
    *,
    status_value: Literal["ok", "degraded", "down"],
    readiness: bool,
) -> dict[str, Any]:
    unhealthy = 0 if readiness else 1
    return {
        "status": status_value,
        "healthy": readiness,
        "readiness": readiness,
        "liveness": True,
        "latency_ms": 1.5,
        "summary": {"total": 1, "healthy": 1 - unhealthy, "unhealthy": unhealthy},
        "checks": {
            "mongodb": {
                "healthy": readiness,
                "latency_ms": 1.5,
                "message": "mongodb ok" if readiness else "mongodb unavailable",
            }
        },
    }


class _FakeManager:
    def __init__(
        self,
        payload: dict[str, Any],
        *,
        error: Exception | None = None,
    ) -> None:
        self.payload = payload
        self.error = error
        self.include_optional_checks_calls: list[bool] = []

    async def health_payload(
        self,
        *,
        include_optional_checks: bool = True,
        **_: Any,
    ) -> dict[str, Any]:
        self.include_optional_checks_calls.append(include_optional_checks)
        if self.error is not None:
            raise self.error
        return self.payload


def _create_test_app(monkeypatch, manager: _FakeManager | None):
    monkeypatch.setattr("src.adapters.main.get_settings", lambda: _make_settings())
    monkeypatch.setattr("src.adapters.main.init_services", AsyncMock())
    monkeypatch.setattr("src.adapters.main.shutdown_services", AsyncMock())
    monkeypatch.setattr(
        "src.adapters.api.routes.health.get_runtime_manager",
        lambda: manager,
    )
    return create_app()


def test_health_endpoint_uses_commons_runtime_payload(monkeypatch) -> None:
    payload = _make_payload(status_value="ok", readiness=True)
    manager = _FakeManager(payload)
    app = _create_test_app(monkeypatch, manager)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == payload
    assert manager.include_optional_checks_calls == [True]


def test_liveness_endpoint_returns_ok(monkeypatch) -> None:
    app = _create_test_app(monkeypatch, manager=None)

    with TestClient(app) as client:
        response = client.get("/health/live")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


def test_readiness_uses_runtime_payload_with_200(monkeypatch) -> None:
    payload = _make_payload(status_value="ok", readiness=True)
    manager = _FakeManager(payload)
    app = _create_test_app(monkeypatch, manager)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == status.HTTP_200_OK
    assert response.json() == payload
    assert manager.include_optional_checks_calls == [False]


def test_readiness_returns_503_when_runtime_not_ready(monkeypatch) -> None:
    payload = _make_payload(status_value="degraded", readiness=False)
    manager = _FakeManager(payload)
    app = _create_test_app(monkeypatch, manager)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert response.json() == payload
    assert manager.include_optional_checks_calls == [False]


def test_health_and_readiness_report_unavailable_runtime_manager(monkeypatch) -> None:
    app = _create_test_app(monkeypatch, manager=None)

    with TestClient(app) as client:
        health_response = client.get("/health")
        ready_response = client.get("/health/ready")

    assert health_response.status_code == status.HTTP_200_OK
    assert ready_response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert health_response.json() == ready_response.json()

    payload = health_response.json()
    assert payload["status"] == "down"
    assert payload["healthy"] is False
    assert payload["readiness"] is False
    assert payload["liveness"] is True
    assert payload["summary"] == {"total": 1, "healthy": 0, "unhealthy": 1}
    assert payload["checks"]["runtime_manager"]["healthy"] is False


def test_health_returns_down_payload_when_runtime_health_fails(monkeypatch) -> None:
    manager = _FakeManager(
        _make_payload(status_value="ok", readiness=True),
        error=RuntimeError("boom"),
    )
    app = _create_test_app(monkeypatch, manager)

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["status"] == "down"
    assert payload["readiness"] is False
    assert payload["checks"]["runtime_manager"]["details"] == {
        "error_type": "RuntimeError"
    }
    assert manager.include_optional_checks_calls == [True]
