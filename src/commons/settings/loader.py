"""Settings loader with hierarchical configuration support."""

import json
import os
from pathlib import Path
from typing import Any

from src.commons.settings.models import Settings


class SettingsLoader:
    """Loads and merges configuration from multiple sources.

    Configuration precedence (highest to lowest):
    1. Environment variables
    2. Environment-specific config (appsettings.{env}.json)
    3. Base config (appsettings.json)
    """

    def __init__(
        self,
        config_dir: Path | None = None,
        environment: str | None = None,
    ) -> None:
        """Initialize the settings loader.

        Args:
            config_dir: Directory containing configuration files.
                       Defaults to 'config' in current working directory.
            environment: Environment name (dev, staging, prod).
                        Defaults to YOUTUBE_RAG__APP__ENVIRONMENT or 'dev'.
        """
        self.config_dir = config_dir or Path("config")
        self.environment = environment or os.getenv(
            "YOUTUBE_RAG__APP__ENVIRONMENT", "dev"
        )

    def load(self) -> Settings:
        """Load settings with proper precedence.

        Returns:
            Fully resolved Settings instance.
        """
        # 1. Load base config
        config = self._load_json("appsettings.json")

        # 2. Merge environment-specific config
        env_config = self._load_json(f"appsettings.{self.environment}.json")
        config = self._deep_merge(config, env_config)

        # 3. Create Settings (env vars loaded automatically by Pydantic)
        return Settings(**config)

    def _load_json(self, filename: str) -> dict[str, Any]:
        """Load JSON config file.

        Args:
            filename: Name of the config file.

        Returns:
            Parsed JSON as dictionary, or empty dict if file doesn't exist.
        """
        path = self.config_dir / filename
        if path.exists():
            with path.open(encoding="utf-8") as f:
                return dict(json.load(f))
        return {}

    def _deep_merge(
        self,
        base: dict[str, Any],
        override: dict[str, Any],
    ) -> dict[str, Any]:
        """Deep merge two dictionaries.

        Args:
            base: Base dictionary.
            override: Dictionary with values to override.

        Returns:
            Merged dictionary.
        """
        result = base.copy()
        for key, value in override.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result


# Global settings instance
_settings: Settings | None = None


def get_settings(
    config_dir: Path | None = None,
    environment: str | None = None,
    *,
    reload: bool = False,
) -> Settings:
    """Get or create the global settings instance.

    Args:
        config_dir: Optional config directory override.
        environment: Optional environment override.
        reload: Force reload settings from files.

    Returns:
        Settings instance.
    """
    global _settings  # noqa: PLW0603
    if _settings is None or reload:
        loader = SettingsLoader(config_dir=config_dir, environment=environment)
        _settings = loader.load()
    return _settings


def reset_settings() -> None:
    """Reset the global settings instance. Useful for testing."""
    global _settings  # noqa: PLW0603
    _settings = None
