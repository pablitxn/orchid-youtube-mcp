"""Langfuse compatibility wrapper backed by orchid_commons observability."""

from __future__ import annotations

import contextlib
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from orchid_commons import (
    LangfuseClient,
    LangfuseClientSettings,
    create_langfuse_client,
    get_default_langfuse_client,
    set_default_langfuse_client,
)

if TYPE_CHECKING:
    from collections.abc import Generator

    from src.commons.settings.models import LangfuseSettings

logger = logging.getLogger(__name__)
_current_trace: ContextVar[Any] = ContextVar("youtube_mcp_langfuse_trace", default=None)


@dataclass(slots=True)
class _GenerationHandle:
    """Handle for an in-flight generation context."""

    observation: Any
    context_manager: contextlib.AbstractContextManager[Any]


def init_langfuse(settings: LangfuseSettings) -> None:
    """Initialize default Langfuse client from legacy youtube-mcp settings."""
    client_settings = LangfuseClientSettings(
        enabled=settings.enabled,
        public_key=settings.public_key or None,
        secret_key=settings.secret_key or None,
        base_url=settings.host,
        timeout_seconds=5,
        flush_at=settings.flush_at,
        flush_interval_seconds=settings.flush_interval,
        sample_rate=settings.sample_rate,
        debug=settings.debug,
    )

    client = create_langfuse_client(
        settings=client_settings,
        register_as_default=True,
    )

    if client.enabled:
        logger.info("Langfuse initialized", extra={"host": client.settings.base_url})
    else:
        logger.info(
            "Langfuse disabled",
            extra={"reason": client.disabled_reason},
        )


def shutdown_langfuse() -> None:
    """Shutdown and clear the default Langfuse client."""
    client = get_default_langfuse_client()
    if client is None:
        return

    try:
        client.flush()
        client.shutdown()
    except Exception as e:
        logger.error("Error shutting down Langfuse", extra={"error": str(e)})
    finally:
        set_default_langfuse_client(None)


def get_langfuse() -> LangfuseClient | None:
    """Get the process-wide Langfuse client instance."""
    return get_default_langfuse_client()


def is_langfuse_enabled() -> bool:
    """Check if Langfuse tracing is enabled."""
    client = get_default_langfuse_client()
    return bool(client is not None and client.enabled)


@contextmanager
def langfuse_trace(
    name: str,
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> Generator[Any, None, None]:
    """Context manager for creating a Langfuse trace-like span."""
    client = _get_enabled_client()
    if client is None:
        yield None
        return

    span_metadata: dict[str, Any] = dict(metadata or {})
    if user_id is not None:
        span_metadata.setdefault("user_id", user_id)
    if session_id is not None:
        span_metadata.setdefault("session_id", session_id)
    if tags is not None:
        span_metadata.setdefault("tags", tags)

    token = None
    try:
        with client.start_span(name=name, metadata=span_metadata or None) as span:
            token = _current_trace.set(span)
            yield span
    except Exception as e:
        logger.error("Error creating Langfuse trace", extra={"error": str(e)})
        yield None
    finally:
        _current_trace.set(None)
        if token is not None:
            with contextlib.suppress(ValueError):
                _current_trace.reset(token)


def get_current_trace() -> Any:
    """Get the current trace/span from context."""
    return _current_trace.get()


def create_llm_generation(
    name: str,
    model: str,
    input_messages: list[dict[str, Any]],
    model_parameters: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    trace: Any = None,
) -> Any:
    """Create a generation observation compatible with legacy callers."""
    client = _get_enabled_client()
    if client is None:
        return None

    trace_id = _extract_trace_id(trace)

    try:
        context_manager = client.start_generation(
            name=name,
            model=model,
            input=input_messages,
            metadata=metadata,
            model_parameters=model_parameters,
            trace_id=trace_id,
        )
        observation = context_manager.__enter__()
        return _GenerationHandle(
            observation=observation,
            context_manager=context_manager,
        )
    except Exception as e:
        logger.error("Error creating LLM generation", extra={"error": str(e)})
        return None


def end_llm_generation(
    generation: Any,
    output: str | dict[str, Any] | None,
    usage: dict[str, int] | None = None,
    metadata: dict[str, Any] | None = None,
    level: str = "DEFAULT",
    status_message: str | None = None,
) -> None:
    """Finalize a generation observation."""
    if generation is None:
        return

    if isinstance(generation, _GenerationHandle):
        try:
            _safe_observation_update(
                generation.observation,
                output=output,
                usage_details=usage,
                metadata=metadata,
                level=level,
                status_message=status_message,
            )
        finally:
            _close_generation(generation.context_manager)
        return

    # Backward compatibility with direct SDK generation objects.
    end = getattr(generation, "end", None)
    if callable(end):
        try:
            end(
                output=output,
                usage=usage,
                metadata=metadata,
                level=level,
                status_message=status_message,
            )
        except Exception as e:
            logger.error("Error ending LLM generation", extra={"error": str(e)})


def flush_langfuse() -> None:
    """Flush pending Langfuse events."""
    client = get_default_langfuse_client()
    if client is None:
        return

    try:
        client.flush()
    except Exception as e:
        logger.error("Error flushing Langfuse", extra={"error": str(e)})


def _get_enabled_client() -> LangfuseClient | None:
    client = get_default_langfuse_client()
    if client is None or not client.enabled:
        return None
    return client


def _extract_trace_id(trace: Any) -> str | None:
    if trace is None:
        return None

    for attr in ("trace_id", "id"):
        value = getattr(trace, attr, None)
        if value:
            return str(value)

    if isinstance(trace, dict):
        value = trace.get("trace_id") or trace.get("id")
        if value:
            return str(value)

    return None


def _safe_observation_update(observation: Any, **kwargs: Any) -> None:
    update = getattr(observation, "update", None)
    if update is None or not callable(update):
        return

    payload = {key: value for key, value in kwargs.items() if value is not None}
    if not payload:
        return

    try:
        update(**payload)
    except Exception:
        return


def _close_generation(context_manager: contextlib.AbstractContextManager[Any]) -> None:
    with contextlib.suppress(Exception):
        context_manager.__exit__(None, None, None)
