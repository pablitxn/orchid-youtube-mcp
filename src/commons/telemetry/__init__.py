"""Telemetry module - logging, tracing, and metrics."""

from src.commons.telemetry.decorators import LogContext, log_exceptions, timed, trace
from src.commons.telemetry.logger import (
    JsonFormatter,
    TextFormatter,
    clear_log_context,
    configure_logging,
    get_correlation_id,
    get_log_context,
    get_logger,
    set_correlation_id,
    set_log_context,
)

__all__ = [
    # Decorators
    "trace",
    "log_exceptions",
    "timed",
    "LogContext",
    # Logger
    "get_logger",
    "configure_logging",
    "JsonFormatter",
    "TextFormatter",
    # Correlation ID
    "get_correlation_id",
    "set_correlation_id",
    # Log Context
    "get_log_context",
    "set_log_context",
    "clear_log_context",
]
