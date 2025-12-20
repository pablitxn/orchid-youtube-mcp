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

    ENV_PREFIX = "YOUTUBE_RAG__"

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

        # 3. Merge environment variables (highest precedence)
        env_overrides = self._load_env_vars()
        config = self._deep_merge(config, env_overrides)

        # 4. Create Settings with merged config
        return Settings(**config)

    def _load_env_vars(self) -> dict[str, Any]:
        """Load environment variables with the YOUTUBE_RAG__ prefix.

        Parses env vars like YOUTUBE_RAG__DOCUMENT_DB__HOST into nested dicts:
        {"document_db": {"host": "value"}}

        Returns:
            Nested dictionary of environment variable overrides.
        """
        result: dict[str, Any] = {}

        for key, value in os.environ.items():
            if not key.startswith(self.ENV_PREFIX):
                continue

            # Remove prefix and split by double underscore
            key_path = key[len(self.ENV_PREFIX) :].lower().split("__")

            # Navigate/create nested structure
            current = result
            for part in key_path[:-1]:
                if part not in current:
                    current[part] = {}
                current = current[part]

            # Set the final value, attempting type coercion
            final_key = key_path[-1]
            current[final_key] = self._coerce_value(value)

        return result

    def _coerce_value(self, value: str) -> Any:
        """Coerce string environment variable to appropriate type.

        Args:
            value: String value from environment.

        Returns:
            Coerced value (bool, int, float, or original string).
        """
        # Boolean
        if value.lower() in ("true", "false"):
            return value.lower() == "true"

        # Try integer
        try:
            return int(value)
        except ValueError:
            pass

        # Try float
        try:
            return float(value)
        except ValueError:
            pass

        # Try JSON (for lists/dicts like CORS_ORIGINS)
        if value.startswith(("[", "{")):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                pass

        return value

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
