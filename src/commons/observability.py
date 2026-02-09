"""Shared observability bootstrap based on orchid_commons primitives."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock
from typing import TYPE_CHECKING

from orchid_commons import (
    AppSettings,
    LangfuseClient,
    bootstrap_logging_from_app_settings,
    bootstrap_observability,
    create_langfuse_client,
    set_default_langfuse_client,
    shutdown_observability,
)

if TYPE_CHECKING:
    from src.commons.settings.models import Settings

_UVICORN_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


@dataclass(slots=True)
class ObservabilityRuntimeState:
    """In-process observability bootstrap state."""

    app_settings: AppSettings
    environment: str
    logging_bootstrapped: bool = False
    uvicorn_logging_configured: bool = False
    observability_bootstrapped: bool = False
    langfuse_client: LangfuseClient | None = None


class _StateHolder:
    state: ObservabilityRuntimeState | None = None
    lock = Lock()


def bootstrap_process_logging(
    settings: Settings,
    *,
    configure_uvicorn_logging: bool = False,
) -> ObservabilityRuntimeState:
    """Bootstrap process logging once, with optional uvicorn logger wiring."""
    with _StateHolder.lock:
        state = _StateHolder.state
        if state is None:
            from src.commons.runtime import load_shared_app_settings

            shared_settings = load_shared_app_settings(settings.app.environment)
            state = ObservabilityRuntimeState(
                app_settings=shared_settings,
                environment=settings.app.environment,
            )
            _StateHolder.state = state

        if not state.logging_bootstrapped:
            bootstrap_logging_from_app_settings(
                state.app_settings,
                env=state.environment,
                logger=logging.getLogger(),
                force=True,
            )
            state.logging_bootstrapped = True

        if configure_uvicorn_logging and not state.uvicorn_logging_configured:
            _configure_uvicorn_logging(
                app_settings=state.app_settings,
                environment=state.environment,
            )
            state.uvicorn_logging_configured = True

        return state


def bootstrap_process_observability(
    settings: Settings,
    *,
    configure_uvicorn_logging: bool = False,
) -> ObservabilityRuntimeState:
    """Bootstrap OpenTelemetry + Langfuse once per process."""
    bootstrap_process_logging(
        settings,
        configure_uvicorn_logging=configure_uvicorn_logging,
    )

    with _StateHolder.lock:
        # Re-resolve state because bootstrap_process_logging releases the lock.
        current_state = _StateHolder.state
        if current_state is None:
            raise RuntimeError("Observability state missing after logging bootstrap")

        if not current_state.observability_bootstrapped:
            bootstrap_observability(
                current_state.app_settings,
                environment=current_state.environment,
            )
            current_state.langfuse_client = create_langfuse_client(
                app_settings=current_state.app_settings,
                register_as_default=True,
            )
            current_state.observability_bootstrapped = True

        return current_state


def shutdown_process_observability() -> None:
    """Shutdown observability backends and reset process bootstrap state."""
    with _StateHolder.lock:
        state = _StateHolder.state
        _StateHolder.state = None

    if state is None:
        return

    if state.langfuse_client is not None:
        try:
            state.langfuse_client.flush()
            state.langfuse_client.shutdown()
        except Exception:
            logging.getLogger(__name__).exception("Failed to shutdown Langfuse client")
        finally:
            state.langfuse_client = None

    set_default_langfuse_client(None)
    shutdown_observability()


def _configure_uvicorn_logging(*, app_settings: AppSettings, environment: str) -> None:
    for logger_name in _UVICORN_LOGGERS:
        bootstrap_logging_from_app_settings(
            app_settings,
            env=environment,
            logger=logging.getLogger(logger_name),
            force=True,
        )


__all__ = [
    "ObservabilityRuntimeState",
    "bootstrap_process_logging",
    "bootstrap_process_observability",
    "shutdown_process_observability",
]
