"""Shared runtime bootstrap for startup/shutdown lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from orchid_commons import (
    ResourceManager,
    ResourceSettings,
    load_config,
    register_factory,
)
from orchid_commons.blob import register_multi_bucket_factory

from src.commons.infrastructure.documentdb import DocumentDBBase, MongoDBDocumentDB
from src.commons.infrastructure.vectordb import QdrantVectorDB, VectorDBBase

if TYPE_CHECKING:
    from orchid_commons.config.models import AppSettings
    from orchid_commons.config.resources import (
        MongoDbSettings,
        QdrantSettings,
    )

    from src.commons.settings.models import Settings

CONFIG_DIR = Path("config")
REQUIRED_RESOURCES = ("multi_bucket", "qdrant", "mongodb")

_FACTORIES_REGISTERED = False


def _resolve_qdrant_target(settings: QdrantSettings) -> tuple[str, int, bool]:
    if settings.host:
        return settings.host, settings.port, settings.use_ssl

    if settings.url is None:
        raise ValueError("Qdrant resource requires host or url")

    parsed = urlparse(settings.url)
    if parsed.hostname is None:
        raise ValueError(f"Invalid Qdrant URL: {settings.url}")

    use_ssl = settings.use_ssl or parsed.scheme == "https"
    default_port = 443 if use_ssl else 80
    return parsed.hostname, parsed.port or default_port, use_ssl


async def _create_qdrant_resource(settings: QdrantSettings) -> VectorDBBase:
    host, port, use_ssl = _resolve_qdrant_target(settings)
    return QdrantVectorDB(
        host=host,
        port=port,
        grpc_port=settings.grpc_port,
        api_key=settings.api_key,
        https=use_ssl,
    )


async def _create_mongodb_resource(settings: MongoDbSettings) -> DocumentDBBase:
    return MongoDBDocumentDB(
        connection_string=settings.uri,
        database_name=settings.database,
    )


def register_runtime_factories() -> None:
    """Register youtube-mcp resource factories once."""
    global _FACTORIES_REGISTERED  # noqa: PLW0603

    if _FACTORIES_REGISTERED:
        return

    register_multi_bucket_factory("multi_bucket")
    register_factory("qdrant", "qdrant", _create_qdrant_resource)
    register_factory("mongodb", "mongodb", _create_mongodb_resource)

    _FACTORIES_REGISTERED = True


@lru_cache
def load_shared_app_settings(environment: str) -> AppSettings:
    """Load shared appsettings using orchid_commons model."""
    return load_config(config_dir=CONFIG_DIR, env=environment)


@dataclass(slots=True)
class RuntimeState:
    """Holds the active runtime state initialized at startup."""

    manager: ResourceManager
    shared_settings: AppSettings


class _RuntimeHolder:
    state: RuntimeState | None = None


async def startup_runtime(settings: Settings) -> RuntimeState:
    """Initialize shared runtime and required resources."""
    if _RuntimeHolder.state is not None:
        return _RuntimeHolder.state

    register_runtime_factories()

    shared_settings = load_shared_app_settings(settings.app.environment)
    resource_settings = ResourceSettings.from_app_settings(shared_settings)

    manager = ResourceManager()
    await manager.startup(
        resource_settings,
        required=list(REQUIRED_RESOURCES),
    )

    state = RuntimeState(manager=manager, shared_settings=shared_settings)
    _RuntimeHolder.state = state
    return state


async def shutdown_runtime() -> None:
    """Shutdown runtime resources and clear caches."""
    state = _RuntimeHolder.state
    _RuntimeHolder.state = None
    load_shared_app_settings.cache_clear()

    if state is None:
        return

    await state.manager.close_all()


def get_runtime_manager() -> ResourceManager | None:
    """Return current runtime resource manager, if initialized."""
    state = _RuntimeHolder.state
    if state is None:
        return None
    return state.manager


def reset_runtime_state() -> None:
    """Reset runtime holder and cache for testing."""
    _RuntimeHolder.state = None
    load_shared_app_settings.cache_clear()


__all__ = [
    "REQUIRED_RESOURCES",
    "RuntimeState",
    "get_runtime_manager",
    "load_shared_app_settings",
    "register_runtime_factories",
    "reset_runtime_state",
    "shutdown_runtime",
    "startup_runtime",
]
