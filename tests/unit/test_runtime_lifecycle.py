"""Unit tests for shared runtime lifecycle wiring."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.runtime import REQUIRED_RESOURCES, reset_runtime_state


@pytest.fixture(autouse=True)
def reset_runtime():
    """Reset runtime singleton state before/after each test."""
    reset_runtime_state()
    yield
    reset_runtime_state()


class TestRuntimeBootstrap:
    """Tests for runtime startup/shutdown orchestration."""

    @pytest.mark.asyncio
    async def test_startup_runtime_uses_required_resources(self):
        """Startup should initialize manager with fail-fast required resources."""
        from src.infrastructure.runtime import startup_runtime

        settings = MagicMock()
        settings.app.environment = "dev"

        shared_settings = MagicMock()
        resource_settings = MagicMock()
        manager = AsyncMock()

        with (
            patch("src.infrastructure.runtime.register_runtime_factories"),
            patch(
                "src.infrastructure.runtime.load_shared_app_settings",
                return_value=shared_settings,
            ),
            patch(
                "src.infrastructure.runtime.ResourceSettings.from_app_settings",
                return_value=resource_settings,
            ),
            patch("src.infrastructure.runtime.ResourceManager", return_value=manager),
        ):
            state = await startup_runtime(settings)

        assert state.manager is manager
        manager.startup.assert_awaited_once_with(
            resource_settings,
            required=list(REQUIRED_RESOURCES),
        )

    @pytest.mark.asyncio
    async def test_shutdown_runtime_closes_manager(self):
        """Shutdown should close manager-created resources exactly once."""
        from src.infrastructure.runtime import shutdown_runtime, startup_runtime

        settings = MagicMock()
        settings.app.environment = "dev"

        shared_settings = MagicMock()
        resource_settings = MagicMock()
        manager = AsyncMock()

        with (
            patch("src.infrastructure.runtime.register_runtime_factories"),
            patch(
                "src.infrastructure.runtime.load_shared_app_settings",
                return_value=shared_settings,
            ),
            patch(
                "src.infrastructure.runtime.ResourceSettings.from_app_settings",
                return_value=resource_settings,
            ),
            patch("src.infrastructure.runtime.ResourceManager", return_value=manager),
        ):
            await startup_runtime(settings)
            await shutdown_runtime()
            await shutdown_runtime()

        manager.close_all.assert_awaited_once()


class TestDependencyLifecycle:
    """Tests for API dependency lifecycle helpers."""

    @pytest.mark.asyncio
    async def test_init_services_uses_runtime_manager(self):
        """init_services should bind factory to shared runtime manager."""
        from src.adapters.dependencies import init_services

        settings = MagicMock()
        manager = MagicMock()
        runtime_state = SimpleNamespace(manager=manager)

        factory = MagicMock()

        with (
            patch(
                "src.adapters.dependencies.bootstrap_process_observability"
            ) as bootstrap_process_observability,
            patch(
                "src.adapters.dependencies.startup_runtime",
                new=AsyncMock(return_value=runtime_state),
            ),
            patch(
                "src.adapters.dependencies.get_factory",
                return_value=factory,
            ) as get_factory,
        ):
            await init_services(settings)

        bootstrap_process_observability.assert_called_once_with(
            settings,
            configure_uvicorn_logging=False,
        )
        get_factory.assert_called_once_with(settings, resource_manager=manager)
        factory.get_blob_storage.assert_called_once()
        factory.get_vector_db.assert_called_once()
        factory.get_document_db.assert_called_once()

    @pytest.mark.asyncio
    async def test_init_services_can_configure_uvicorn_logging(self):
        """init_services should pass uvicorn logging flag to observability bootstrap."""
        from src.adapters.dependencies import init_services

        settings = MagicMock()
        manager = MagicMock()
        runtime_state = SimpleNamespace(manager=manager)
        factory = MagicMock()

        with (
            patch(
                "src.adapters.dependencies.bootstrap_process_observability"
            ) as bootstrap_process_observability,
            patch(
                "src.adapters.dependencies.startup_runtime",
                new=AsyncMock(return_value=runtime_state),
            ),
            patch(
                "src.adapters.dependencies.get_factory",
                return_value=factory,
            ),
        ):
            await init_services(settings, configure_uvicorn_logging=True)

        bootstrap_process_observability.assert_called_once_with(
            settings,
            configure_uvicorn_logging=True,
        )

    @pytest.mark.asyncio
    async def test_shutdown_services_always_cleans_runtime_state(self):
        """shutdown_services should run cleanup even when factory is missing."""
        from src.adapters import dependencies

        with (
            patch(
                "src.adapters.dependencies.get_factory",
                side_effect=ValueError("factory not initialized"),
            ),
            patch(
                "src.adapters.dependencies.shutdown_process_observability"
            ) as shutdown_obs,
            patch("src.adapters.dependencies.reset_factory"),
            patch(
                "src.adapters.dependencies.shutdown_runtime",
                new=AsyncMock(),
            ) as shutdown_runtime,
            patch.object(dependencies.get_settings, "cache_clear") as cache_clear,
        ):
            await dependencies.shutdown_services()

        shutdown_obs.assert_called_once()
        shutdown_runtime.assert_awaited_once()
        cache_clear.assert_called_once()
