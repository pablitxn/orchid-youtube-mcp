"""Telemetry decorators for tracing, timing, and exception logging."""

import functools
import inspect
import logging
import time
from collections.abc import Callable
from typing import Any, ParamSpec, TypeVar, overload

from src.commons.telemetry.logger import get_logger

P = ParamSpec("P")
R = TypeVar("R")


@overload
def trace(
    func: Callable[P, R],
) -> Callable[P, R]: ...


@overload
def trace(
    *,
    logger: logging.Logger | None = None,
    log_args: bool = True,
    log_result: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def trace(
    func: Callable[P, R] | None = None,
    *,
    logger: logging.Logger | None = None,
    log_args: bool = True,
    log_result: bool = False,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to trace function entry and exit.

    Can be used with or without arguments:
        @trace
        def my_func(): ...

        @trace(log_result=True)
        def my_func(): ...

    Args:
        func: The function to decorate (when used without parentheses).
        logger: Optional logger instance. Defaults to function's module logger.
        log_args: Whether to log function arguments.
        log_result: Whether to log function result.

    Returns:
        Decorated function.
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        log = logger or get_logger(fn.__module__)

        @functools.wraps(fn)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            func_name = fn.__qualname__

            # Log entry
            entry_msg = f"Entering {func_name}"
            if log_args:
                entry_msg += f" with args={args}, kwargs={kwargs}"
            log.debug(entry_msg)

            try:
                result = fn(*args, **kwargs)

                # Log exit
                exit_msg = f"Exiting {func_name}"
                if log_result:
                    exit_msg += f" with result={result}"
                log.debug(exit_msg)

                return result
            except Exception as e:
                log.debug(f"Exiting {func_name} with exception: {e!r}")
                raise

        @functools.wraps(fn)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            func_name = fn.__qualname__

            # Log entry
            entry_msg = f"Entering {func_name}"
            if log_args:
                entry_msg += f" with args={args}, kwargs={kwargs}"
            log.debug(entry_msg)

            try:
                result = await fn(*args, **kwargs)  # type: ignore[misc]

                # Log exit
                exit_msg = f"Exiting {func_name}"
                if log_result:
                    exit_msg += f" with result={result}"
                log.debug(exit_msg)

                return result  # type: ignore[no-any-return]
            except Exception as e:
                log.debug(f"Exiting {func_name} with exception: {e!r}")
                raise

        if inspect.iscoroutinefunction(fn):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper

    if func is not None:
        return decorator(func)
    return decorator


@overload
def log_exceptions(
    func: Callable[P, R],
) -> Callable[P, R]: ...


@overload
def log_exceptions(
    *,
    logger: logging.Logger | None = None,
    level: int = logging.ERROR,
    reraise: bool = True,
    message: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def log_exceptions(
    func: Callable[P, R] | None = None,
    *,
    logger: logging.Logger | None = None,
    level: int = logging.ERROR,
    reraise: bool = True,
    message: str | None = None,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to log exceptions with context.

    Args:
        func: The function to decorate (when used without parentheses).
        logger: Optional logger instance.
        level: Log level for exceptions.
        reraise: Whether to re-raise the exception after logging.
        message: Optional custom message prefix.

    Returns:
        Decorated function.
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        log = logger or get_logger(fn.__module__)

        @functools.wraps(fn)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                msg = message or f"Exception in {fn.__qualname__}"
                log.log(
                    level,
                    msg,
                    exc_info=True,
                    extra={"exception_type": type(e).__name__},
                )
                if reraise:
                    raise
                return None  # type: ignore[return-value]

        @functools.wraps(fn)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            try:
                result = await fn(*args, **kwargs)  # type: ignore[misc]
                return result  # type: ignore[no-any-return]
            except Exception as e:
                msg = message or f"Exception in {fn.__qualname__}"
                log.log(
                    level,
                    msg,
                    exc_info=True,
                    extra={"exception_type": type(e).__name__},
                )
                if reraise:
                    raise
                return None  # type: ignore[return-value]

        if inspect.iscoroutinefunction(fn):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper

    if func is not None:
        return decorator(func)
    return decorator


@overload
def timed(
    func: Callable[P, R],
) -> Callable[P, R]: ...


@overload
def timed(
    *,
    logger: logging.Logger | None = None,
    level: int = logging.DEBUG,
    threshold_ms: float | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def timed(
    func: Callable[P, R] | None = None,
    *,
    logger: logging.Logger | None = None,
    level: int = logging.DEBUG,
    threshold_ms: float | None = None,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator to measure and log function execution time.

    Args:
        func: The function to decorate (when used without parentheses).
        logger: Optional logger instance.
        level: Log level for timing messages.
        threshold_ms: Only log if execution exceeds this threshold in milliseconds.

    Returns:
        Decorated function.
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        log = logger or get_logger(fn.__module__)

        @functools.wraps(fn)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                if threshold_ms is None or elapsed_ms >= threshold_ms:
                    log.log(
                        level,
                        f"{fn.__qualname__} completed",
                        extra={"duration_ms": round(elapsed_ms, 2)},
                    )

        @functools.wraps(fn)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            start = time.perf_counter()
            try:
                result = await fn(*args, **kwargs)  # type: ignore[misc]
                return result  # type: ignore[no-any-return]
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000
                if threshold_ms is None or elapsed_ms >= threshold_ms:
                    log.log(
                        level,
                        f"{fn.__qualname__} completed",
                        extra={"duration_ms": round(elapsed_ms, 2)},
                    )

        if inspect.iscoroutinefunction(fn):
            return async_wrapper  # type: ignore[return-value]
        return sync_wrapper

    if func is not None:
        return decorator(func)
    return decorator


class LogContext:
    """Context manager for adding temporary logging context."""

    def __init__(self, **kwargs: Any) -> None:
        """Initialize with context values.

        Args:
            **kwargs: Key-value pairs to add to logging context.
        """
        self.context = kwargs
        self._previous_context: dict[str, Any] = {}

    def __enter__(self) -> "LogContext":
        """Enter the context, adding values to log context."""
        from src.commons.telemetry.logger import get_log_context, log_context_var

        self._previous_context = get_log_context()
        new_context = {**self._previous_context, **self.context}
        log_context_var.set(new_context)
        return self

    def __exit__(self, *args: Any) -> None:
        """Exit the context, restoring previous values."""
        from src.commons.telemetry.logger import log_context_var

        log_context_var.set(self._previous_context)
