"""Langfuse integration for LLM observability."""

from __future__ import annotations

import contextlib
import logging
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from langfuse import Langfuse

if TYPE_CHECKING:
    from collections.abc import Generator

    from langfuse.client import StatefulGenerationClient, StatefulTraceClient

    from src.commons.settings.models import LangfuseSettings

logger = logging.getLogger(__name__)


@dataclass
class _LangfuseState:
    """Internal state holder for Langfuse client."""

    client: Langfuse | None = None
    enabled: bool = False
    current_trace: ContextVar[Any] = field(
        default_factory=lambda: ContextVar("current_trace", default=None)
    )


# Singleton state instance
_state = _LangfuseState()


def init_langfuse(settings: LangfuseSettings) -> None:
    """Initialize the global Langfuse client.

    Args:
        settings: Langfuse configuration settings.
    """
    if not settings.enabled:
        logger.info("Langfuse is disabled")
        _state.enabled = False
        return

    if not settings.public_key or not settings.secret_key:
        logger.warning("Langfuse keys not configured, tracing disabled")
        _state.enabled = False
        return

    try:
        _state.client = Langfuse(
            public_key=settings.public_key,
            secret_key=settings.secret_key,
            host=settings.host,
            debug=settings.debug,
            sample_rate=settings.sample_rate,
            flush_at=settings.flush_at,
            flush_interval=settings.flush_interval,
        )
        _state.enabled = True
        logger.info("Langfuse initialized successfully", extra={"host": settings.host})
    except Exception as e:
        logger.error("Failed to initialize Langfuse", extra={"error": str(e)})
        _state.enabled = False


def shutdown_langfuse() -> None:
    """Shutdown and flush the Langfuse client."""
    if _state.client is not None:
        try:
            _state.client.flush()
            _state.client.shutdown()
            logger.info("Langfuse shutdown successfully")
        except Exception as e:
            logger.error("Error shutting down Langfuse", extra={"error": str(e)})
        finally:
            _state.client = None
            _state.enabled = False


def get_langfuse() -> Langfuse | None:
    """Get the global Langfuse client instance.

    Returns:
        The Langfuse client or None if not initialized.
    """
    return _state.client


def is_langfuse_enabled() -> bool:
    """Check if Langfuse tracing is enabled.

    Returns:
        True if Langfuse is enabled and initialized.
    """
    return _state.enabled


@contextmanager
def langfuse_trace(
    name: str,
    user_id: str | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
) -> Generator[StatefulTraceClient | None, None, None]:
    """Context manager for creating a Langfuse trace.

    Args:
        name: Name of the trace.
        user_id: Optional user identifier.
        session_id: Optional session identifier.
        metadata: Optional metadata dictionary.
        tags: Optional list of tags.

    Yields:
        The trace object or None if Langfuse is not enabled.
    """
    if not _state.enabled or _state.client is None:
        yield None
        return

    token = None
    try:
        trace = _state.client.trace(
            name=name,
            user_id=user_id,
            session_id=session_id,
            metadata=metadata or {},
            tags=tags or [],
        )
        token = _state.current_trace.set(trace)
        yield trace
    except Exception as e:
        logger.error("Error creating Langfuse trace", extra={"error": str(e)})
        yield None
    finally:
        _state.current_trace.set(None)
        if token is not None:
            with contextlib.suppress(ValueError):
                _state.current_trace.reset(token)


def get_current_trace() -> StatefulTraceClient | None:
    """Get the current trace from context.

    Returns:
        The current trace or None.
    """
    return _state.current_trace.get()


def create_llm_generation(
    name: str,
    model: str,
    input_messages: list[dict[str, Any]],
    model_parameters: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    trace: StatefulTraceClient | None = None,
) -> StatefulGenerationClient | None:
    """Create a new LLM generation for tracking.

    Args:
        name: Name of the generation (e.g., "chat_completion").
        model: Model identifier.
        input_messages: Input messages sent to the LLM.
        model_parameters: Model parameters (temperature, max_tokens, etc.).
        metadata: Additional metadata.
        trace: Optional trace to attach to. Uses current trace if not provided.

    Returns:
        The generation object for updating with output, or None if disabled.
    """
    if not _state.enabled or _state.client is None:
        return None

    parent = trace or _state.current_trace.get()

    try:
        if parent is not None:
            return parent.generation(
                name=name,
                model=model,
                input=input_messages,
                model_parameters=model_parameters or {},
                metadata=metadata or {},
            )
        # Create standalone generation with new trace
        new_trace = _state.client.trace(name=f"standalone_{name}")
        return new_trace.generation(
            name=name,
            model=model,
            input=input_messages,
            model_parameters=model_parameters or {},
            metadata=metadata or {},
        )
    except Exception as e:
        logger.error("Error creating LLM generation", extra={"error": str(e)})
        return None


def end_llm_generation(
    generation: StatefulGenerationClient | None,
    output: str | dict[str, Any] | None,
    usage: dict[str, int] | None = None,
    metadata: dict[str, Any] | None = None,
    level: str = "DEFAULT",
    status_message: str | None = None,
) -> None:
    """End an LLM generation with output and usage.

    Args:
        generation: The generation object to update.
        output: The LLM output (text or structured).
        usage: Token usage dict with prompt_tokens, completion_tokens, total_tokens.
        metadata: Additional metadata to add.
        level: Log level (DEFAULT, DEBUG, WARNING, ERROR).
        status_message: Optional status message.
    """
    if generation is None:
        return

    try:
        generation.end(
            output=output,
            usage=usage,
            metadata=metadata,
            level=level,
            status_message=status_message,
        )
    except Exception as e:
        logger.error("Error ending LLM generation", extra={"error": str(e)})


def flush_langfuse() -> None:
    """Flush any pending Langfuse events."""
    if _state.client is not None:
        try:
            _state.client.flush()
        except Exception as e:
            logger.error("Error flushing Langfuse", extra={"error": str(e)})
