"""Structured logging with JSON output and correlation ID support."""

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, ClassVar

# Context variable for correlation ID
correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)

# Context variable for additional context
# Note: ContextVar doesn't support default_factory, we handle default in get
log_context_var: ContextVar[dict[str, Any]] = ContextVar("log_context")


def get_correlation_id() -> str | None:
    """Get the current correlation ID."""
    return correlation_id_var.get()


def set_correlation_id(correlation_id: str | None = None) -> str:
    """Set the correlation ID for the current context.

    Args:
        correlation_id: Optional correlation ID. Generated if not provided.

    Returns:
        The correlation ID that was set.
    """
    cid = correlation_id or str(uuid.uuid4())
    correlation_id_var.set(cid)
    return cid


def get_log_context() -> dict[str, Any]:
    """Get the current logging context."""
    try:
        return log_context_var.get().copy()
    except LookupError:
        return {}


def set_log_context(**kwargs: Any) -> None:
    """Set additional context for logging.

    Args:
        **kwargs: Key-value pairs to add to the logging context.
    """
    try:
        ctx = log_context_var.get().copy()
    except LookupError:
        ctx = {}
    ctx.update(kwargs)
    log_context_var.set(ctx)


def clear_log_context() -> None:
    """Clear the logging context."""
    log_context_var.set({})


class JsonFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def __init__(
        self,
        *,
        include_timestamp: bool = True,
        include_level: bool = True,
        include_logger: bool = True,
        include_path: bool = True,
    ) -> None:
        """Initialize the JSON formatter.

        Args:
            include_timestamp: Include timestamp in output.
            include_level: Include log level in output.
            include_logger: Include logger name in output.
            include_path: Include file path and line number.
        """
        super().__init__()
        self.include_timestamp = include_timestamp
        self.include_level = include_level
        self.include_logger = include_logger
        self.include_path = include_path

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as JSON.

        Args:
            record: The log record to format.

        Returns:
            JSON-formatted log string.
        """
        log_data: dict[str, Any] = {}

        if self.include_timestamp:
            log_data["timestamp"] = datetime.now(UTC).isoformat()

        if self.include_level:
            log_data["level"] = record.levelname

        if self.include_logger:
            log_data["logger"] = record.name

        if self.include_path:
            log_data["path"] = f"{record.pathname}:{record.lineno}"

        # Add correlation ID if present
        cid = get_correlation_id()
        if cid:
            log_data["correlation_id"] = cid

        # Add message
        log_data["message"] = record.getMessage()

        # Add context from context var
        context = get_log_context()
        if context:
            log_data["context"] = context

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add any extra fields
        extra_keys = set(record.__dict__.keys()) - {
            "name",
            "msg",
            "args",
            "created",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "module",
            "msecs",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "exc_info",
            "exc_text",
            "thread",
            "threadName",
            "taskName",
            "message",
        }
        for key in extra_keys:
            log_data[key] = getattr(record, key)

        return json.dumps(log_data, default=str)


class TextFormatter(logging.Formatter):
    """Human-readable text formatter with color support."""

    COLORS: ClassVar[dict[str, str]] = {
        "DEBUG": "\033[36m",  # Cyan
        "INFO": "\033[32m",  # Green
        "WARNING": "\033[33m",  # Yellow
        "ERROR": "\033[31m",  # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET: ClassVar[str] = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        """Format the log record as colored text.

        Args:
            record: The log record to format.

        Returns:
            Formatted log string.
        """
        timestamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        color = self.COLORS.get(record.levelname, "")

        # Build the base message
        parts = [
            f"{timestamp}",
            f"{color}{record.levelname:8}{self.RESET}",
            f"[{record.name}]",
        ]

        # Add correlation ID if present
        cid = get_correlation_id()
        if cid:
            parts.append(f"[{cid[:8]}]")

        parts.append(record.getMessage())

        message = " ".join(parts)

        # Add exception if present
        if record.exc_info:
            message += "\n" + self.formatException(record.exc_info)

        return message


def configure_logging(
    level: str = "INFO",
    format_type: str = "json",
    logger_name: str | None = None,
) -> logging.Logger:
    """Configure and return a logger.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        format_type: Output format ('json' or 'text').
        logger_name: Optional logger name. Defaults to root logger.

    Returns:
        Configured logger instance.
    """
    logger = logging.getLogger(logger_name)
    logger.setLevel(getattr(logging, level.upper()))

    # Remove existing handlers
    logger.handlers.clear()

    # Create handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(getattr(logging, level.upper()))

    # Set formatter
    if format_type == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter())

    logger.addHandler(handler)

    # Prevent propagation to root logger
    logger.propagate = False

    return logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger by name.

    Args:
        name: Logger name (usually __name__).

    Returns:
        Logger instance.
    """
    return logging.getLogger(name)
