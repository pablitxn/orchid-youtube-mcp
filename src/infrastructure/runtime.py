"""Shared runtime bootstrap for startup/shutdown lifecycle."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from orchid_commons import (
    ResourceManager,
    load_config,
)
from orchid_commons.blob import register_multi_bucket_factory

if TYPE_CHECKING:
    from orchid_commons.config.models import AppSettings

    from src.infrastructure.settings.models import Settings

CONFIG_DIR = Path("config")
REQUIRED_RESOURCES = ("multi_bucket", "qdrant", "mongodb")

_FACTORIES_REGISTERED = False


def register_runtime_factories() -> None:
    """Register youtube-mcp resource factories once."""
    global _FACTORIES_REGISTERED  # noqa: PLW0603

    if _FACTORIES_REGISTERED:
        return

    # Keep explicit registration for multi-bucket alias used by the app.
    # Qdrant/MongoDB factories are provided by orchid_commons built-ins.
    register_multi_bucket_factory("multi_bucket")

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
    resource_settings = shared_settings.resources

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
