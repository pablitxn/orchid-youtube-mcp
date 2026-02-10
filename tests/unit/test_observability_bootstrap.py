"""Unit tests for shared observability bootstrap helpers."""

from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure import observability


@pytest.fixture(autouse=True)
def reset_observability_state() -> None:
    """Reset bootstrap singleton state before/after each test."""
    observability._StateHolder.state = None
    yield
    observability._StateHolder.state = None


class TestBootstrapProcessObservability:
    """Tests for process-level observability bootstrap idempotency."""

    def test_bootstrap_observability_is_idempotent(self) -> None:
        settings = MagicMock()
        settings.app.environment = "dev"

        shared_settings = MagicMock()
        langfuse_client = MagicMock()

        with (
            patch(
                "src.infrastructure.runtime.load_shared_app_settings",
                return_value=shared_settings,
            ),
            patch(
                "src.infrastructure.observability.bootstrap_logging_from_app_settings"
            ) as bootstrap_logging,
            patch(
                "src.infrastructure.observability.bootstrap_observability"
            ) as bootstrap_otel,
            patch(
                "src.infrastructure.observability.create_langfuse_client",
                return_value=langfuse_client,
            ) as create_client,
        ):
            first = observability.bootstrap_process_observability(settings)
            second = observability.bootstrap_process_observability(settings)

        assert first is second
        bootstrap_logging.assert_called_once()
        bootstrap_otel.assert_called_once_with(shared_settings, environment="dev")
        create_client.assert_called_once_with(
            app_settings=shared_settings,
            register_as_default=True,
        )

    def test_configure_uvicorn_logging_runs_once(self) -> None:
        settings = MagicMock()
        settings.app.environment = "dev"

        shared_settings = MagicMock()

        with (
            patch(
                "src.infrastructure.runtime.load_shared_app_settings",
                return_value=shared_settings,
            ),
            patch(
                "src.infrastructure.observability.bootstrap_logging_from_app_settings"
            ) as bootstrap_logging,
        ):
            observability.bootstrap_process_logging(
                settings,
                configure_uvicorn_logging=True,
            )
            observability.bootstrap_process_logging(
                settings,
                configure_uvicorn_logging=True,
            )

        # One call for root logger + one per uvicorn logger
        assert bootstrap_logging.call_count == 4

    def test_bootstrap_observability_with_uvicorn_logging_is_idempotent(self) -> None:
        settings = MagicMock()
        settings.app.environment = "dev"

        shared_settings = MagicMock()
        langfuse_client = MagicMock()

        with (
            patch(
                "src.infrastructure.runtime.load_shared_app_settings",
                return_value=shared_settings,
            ),
            patch(
                "src.infrastructure.observability.bootstrap_logging_from_app_settings"
            ) as bootstrap_logging,
            patch(
                "src.infrastructure.observability.bootstrap_observability"
            ) as bootstrap_otel,
            patch(
                "src.infrastructure.observability.create_langfuse_client",
                return_value=langfuse_client,
            ) as create_client,
        ):
            observability.bootstrap_process_observability(
                settings,
                configure_uvicorn_logging=True,
            )
            observability.bootstrap_process_observability(
                settings,
                configure_uvicorn_logging=True,
            )

        assert bootstrap_logging.call_count == 4
        bootstrap_otel.assert_called_once_with(shared_settings, environment="dev")
        create_client.assert_called_once_with(
            app_settings=shared_settings,
            register_as_default=True,
        )


class TestShutdownProcessObservability:
    """Tests for observability shutdown."""

    def test_shutdown_flushes_langfuse_and_resets_globals(self) -> None:
        settings = MagicMock()
        settings.app.environment = "dev"

        shared_settings = MagicMock()
        langfuse_client = MagicMock()

        with (
            patch(
                "src.infrastructure.runtime.load_shared_app_settings",
                return_value=shared_settings,
            ),
            patch("src.infrastructure.observability.bootstrap_logging_from_app_settings"),
            patch("src.infrastructure.observability.bootstrap_observability"),
            patch(
                "src.infrastructure.observability.create_langfuse_client",
                return_value=langfuse_client,
            ),
            patch(
                "src.infrastructure.observability.set_default_langfuse_client"
            ) as set_default,
            patch(
                "src.infrastructure.observability.shutdown_observability"
            ) as shutdown_otel,
        ):
            observability.bootstrap_process_observability(settings)
            observability.shutdown_process_observability()

        langfuse_client.flush.assert_called_once()
        langfuse_client.shutdown.assert_called_once()
        set_default.assert_called_once_with(None)
        shutdown_otel.assert_called_once()
        assert observability._StateHolder.state is None
