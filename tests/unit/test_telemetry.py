"""Unit tests for telemetry module."""

import asyncio
import json
import logging

import pytest

from src.commons.telemetry.decorators import LogContext, log_exceptions, timed, trace
from src.commons.telemetry.logger import (
    JsonFormatter,
    TextFormatter,
    clear_log_context,
    configure_logging,
    get_correlation_id,
    get_log_context,
    set_correlation_id,
    set_log_context,
)


class TestCorrelationId:
    """Tests for correlation ID management."""

    def test_set_and_get_correlation_id(self):
        cid = set_correlation_id("test-123")
        assert cid == "test-123"
        assert get_correlation_id() == "test-123"

    def test_auto_generate_correlation_id(self):
        cid = set_correlation_id()
        assert cid is not None
        assert len(cid) == 36  # UUID format

    def test_correlation_id_isolation(self):
        """Test that correlation IDs are isolated per context."""
        set_correlation_id("main-context")

        async def async_task():
            set_correlation_id("async-context")
            return get_correlation_id()

        result = asyncio.run(async_task())
        # The async task should have its own context
        assert result == "async-context"


class TestLogContext:
    """Tests for logging context management."""

    def setup_method(self):
        clear_log_context()

    def teardown_method(self):
        clear_log_context()

    def test_set_and_get_context(self):
        set_log_context(user_id="123", action="test")
        ctx = get_log_context()
        assert ctx["user_id"] == "123"
        assert ctx["action"] == "test"

    def test_clear_context(self):
        set_log_context(key="value")
        clear_log_context()
        assert get_log_context() == {}

    def test_context_is_copied(self):
        set_log_context(key="value")
        ctx = get_log_context()
        ctx["new_key"] = "new_value"
        # Original context should be unchanged
        assert "new_key" not in get_log_context()


class TestJsonFormatter:
    """Tests for JSON log formatter."""

    def test_basic_format(self):
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="/test/file.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["level"] == "INFO"
        assert data["logger"] == "test.logger"
        assert data["message"] == "Test message"
        assert "timestamp" in data
        assert "/test/file.py:42" in data["path"]

    def test_format_with_correlation_id(self):
        set_correlation_id("test-cid")
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["correlation_id"] == "test-cid"

    def test_format_with_context(self):
        set_log_context(request_id="req-123")
        formatter = JsonFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        data = json.loads(output)

        assert data["context"]["request_id"] == "req-123"
        clear_log_context()

    def test_format_with_exception(self):
        formatter = JsonFormatter()
        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            record = logging.LogRecord(
                name="test",
                level=logging.ERROR,
                pathname="",
                lineno=0,
                msg="Error occurred",
                args=(),
                exc_info=sys.exc_info(),
            )

            output = formatter.format(record)
            data = json.loads(output)

            assert "exception" in data
            assert "ValueError" in data["exception"]


class TestTextFormatter:
    """Tests for text log formatter."""

    def test_basic_format(self):
        formatter = TextFormatter()
        record = logging.LogRecord(
            name="test.logger",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)

        assert "INFO" in output
        assert "[test.logger]" in output
        assert "Test message" in output


class TestConfigureLogging:
    """Tests for logger configuration."""

    def test_configure_json_logger(self):
        logger = configure_logging(
            level="DEBUG", format_type="json", logger_name="test.json"
        )
        assert logger.level == logging.DEBUG
        assert len(logger.handlers) == 1
        assert isinstance(logger.handlers[0].formatter, JsonFormatter)

    def test_configure_text_logger(self):
        logger = configure_logging(
            level="INFO", format_type="text", logger_name="test.text"
        )
        assert logger.level == logging.INFO
        assert isinstance(logger.handlers[0].formatter, TextFormatter)


class TestTraceDecorator:
    """Tests for @trace decorator."""

    def test_trace_sync_function(self, caplog):
        @trace
        def my_function(x, y):
            return x + y

        with caplog.at_level(logging.DEBUG):
            result = my_function(1, 2)

        assert result == 3

    def test_trace_async_function(self, caplog):
        @trace
        async def my_async_function(x):
            return x * 2

        with caplog.at_level(logging.DEBUG):
            result = asyncio.run(my_async_function(5))

        assert result == 10

    def test_trace_with_exception(self):
        @trace
        def failing_function():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            failing_function()


class TestLogExceptionsDecorator:
    """Tests for @log_exceptions decorator."""

    def test_log_and_reraise(self, caplog):
        @log_exceptions
        def failing_function():
            raise RuntimeError("Test error")

        with pytest.raises(RuntimeError), caplog.at_level(logging.ERROR):
            failing_function()

    def test_log_without_reraise(self, caplog):
        @log_exceptions(reraise=False)
        def failing_function():
            raise RuntimeError("Test error")

        with caplog.at_level(logging.ERROR):
            result = failing_function()

        assert result is None

    def test_async_log_exceptions(self, caplog):
        @log_exceptions
        async def async_failing():
            raise ValueError("Async error")

        with pytest.raises(ValueError), caplog.at_level(logging.ERROR):
            asyncio.run(async_failing())


class TestTimedDecorator:
    """Tests for @timed decorator."""

    def test_timed_sync_function(self, caplog):
        @timed
        def slow_function():
            import time

            time.sleep(0.01)
            return "done"

        with caplog.at_level(logging.DEBUG):
            result = slow_function()

        assert result == "done"

    def test_timed_async_function(self, caplog):
        @timed
        async def async_slow():
            await asyncio.sleep(0.01)
            return "async done"

        with caplog.at_level(logging.DEBUG):
            result = asyncio.run(async_slow())

        assert result == "async done"

    def test_timed_with_threshold(self, caplog):
        @timed(threshold_ms=1000)  # 1 second threshold
        def fast_function():
            return "fast"

        with caplog.at_level(logging.DEBUG):
            result = fast_function()

        assert result == "fast"
        # Should not log because execution was under threshold


class TestLogContextManager:
    """Tests for LogContext context manager."""

    def setup_method(self):
        clear_log_context()

    def teardown_method(self):
        clear_log_context()

    def test_context_manager_adds_context(self):
        with LogContext(operation="test", user="admin"):
            ctx = get_log_context()
            assert ctx["operation"] == "test"
            assert ctx["user"] == "admin"

    def test_context_manager_restores_context(self):
        set_log_context(existing="value")

        with LogContext(temporary="data"):
            ctx = get_log_context()
            assert ctx["existing"] == "value"
            assert ctx["temporary"] == "data"

        # After exiting, temporary should be gone
        ctx = get_log_context()
        assert ctx["existing"] == "value"
        assert "temporary" not in ctx

    def test_nested_context_managers(self):
        with LogContext(level1="a"):
            with LogContext(level2="b"):
                ctx = get_log_context()
                assert ctx["level1"] == "a"
                assert ctx["level2"] == "b"

            ctx = get_log_context()
            assert ctx["level1"] == "a"
            assert "level2" not in ctx
