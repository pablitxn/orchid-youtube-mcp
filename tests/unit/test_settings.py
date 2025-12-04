"""Unit tests for settings models and loader."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from src.commons.settings.loader import SettingsLoader, get_settings, reset_settings
from src.commons.settings.models import (
    AppSettings,
    BlobStorageSettings,
    ChunkingSettings,
    DocumentDBSettings,
    EmbeddingsSettings,
    LLMSettings,
    ProcessingSettings,
    RateLimitSettings,
    ServerSettings,
    Settings,
    TelemetrySettings,
    TranscriptionSettings,
    VectorDBSettings,
)


class TestAppSettings:
    """Tests for AppSettings model."""

    def test_default_values(self):
        settings = AppSettings()
        assert settings.name == "youtube-rag-server"
        assert settings.version == "0.1.0"
        assert settings.environment == "dev"
        assert settings.debug is False
        assert settings.log_level == "INFO"

    def test_custom_values(self):
        settings = AppSettings(
            name="custom-app",
            environment="prod",
            debug=True,
            log_level="DEBUG",
        )
        assert settings.name == "custom-app"
        assert settings.environment == "prod"
        assert settings.debug is True
        assert settings.log_level == "DEBUG"

    def test_invalid_environment(self):
        with pytest.raises(ValueError):
            AppSettings(environment="invalid")  # type: ignore[arg-type]

    def test_invalid_log_level(self):
        with pytest.raises(ValueError):
            AppSettings(log_level="TRACE")  # type: ignore[arg-type]


class TestServerSettings:
    """Tests for ServerSettings model."""

    def test_default_values(self):
        settings = ServerSettings()
        assert settings.host == "0.0.0.0"
        assert settings.port == 8000
        assert settings.workers == 1
        assert settings.reload is False
        assert settings.cors_origins == ["*"]
        assert settings.api_prefix == "/v1"
        assert settings.docs_enabled is True

    def test_port_validation(self):
        # Valid port
        settings = ServerSettings(port=3000)
        assert settings.port == 3000

        # Invalid port - too low
        with pytest.raises(ValueError):
            ServerSettings(port=0)

        # Invalid port - too high
        with pytest.raises(ValueError):
            ServerSettings(port=70000)

    def test_workers_validation(self):
        settings = ServerSettings(workers=4)
        assert settings.workers == 4

        with pytest.raises(ValueError):
            ServerSettings(workers=0)

        with pytest.raises(ValueError):
            ServerSettings(workers=100)


class TestBlobStorageSettings:
    """Tests for BlobStorageSettings model."""

    def test_default_values(self):
        settings = BlobStorageSettings()
        assert settings.provider == "minio"
        assert settings.endpoint == "localhost:9000"
        assert settings.use_ssl is False
        assert settings.buckets.videos == "rag-videos"
        assert settings.buckets.chunks == "rag-chunks"
        assert settings.buckets.frames == "rag-frames"

    def test_custom_buckets(self):
        from src.commons.settings.models import BucketSettings

        settings = BlobStorageSettings(
            buckets=BucketSettings(
                videos="my-videos",
                chunks="my-chunks",
                frames="my-frames",
            )
        )
        assert settings.buckets.videos == "my-videos"


class TestVectorDBSettings:
    """Tests for VectorDBSettings model."""

    def test_default_values(self):
        settings = VectorDBSettings()
        assert settings.provider == "qdrant"
        assert settings.host == "localhost"
        assert settings.port == 6333
        assert settings.default_limit == 10
        assert settings.score_threshold == 0.7

    def test_collections(self):
        settings = VectorDBSettings()
        assert settings.collections.transcripts == "transcript_embeddings"
        assert settings.collections.frames == "frame_embeddings"
        assert settings.collections.videos == "video_embeddings"


class TestLLMSettings:
    """Tests for LLMSettings model."""

    def test_default_values(self):
        settings = LLMSettings()
        assert settings.provider == "openai"
        assert settings.model == "gpt-4o"
        assert settings.temperature == 0.7
        assert settings.max_tokens == 2048

    def test_temperature_validation(self):
        settings = LLMSettings(temperature=1.5)
        assert settings.temperature == 1.5

        with pytest.raises(ValueError):
            LLMSettings(temperature=-0.1)

        with pytest.raises(ValueError):
            LLMSettings(temperature=2.5)


class TestChunkingSettings:
    """Tests for ChunkingSettings model."""

    def test_default_values(self):
        settings = ChunkingSettings()
        assert settings.transcript.chunk_seconds == 30
        assert settings.transcript.overlap_seconds == 5
        assert settings.frame.interval_seconds == 2.0
        assert settings.video.max_size_mb == 20.0


class TestRootSettings:
    """Tests for root Settings model."""

    def test_default_values(self):
        settings = Settings()
        assert isinstance(settings.app, AppSettings)
        assert isinstance(settings.server, ServerSettings)
        assert isinstance(settings.blob_storage, BlobStorageSettings)
        assert isinstance(settings.vector_db, VectorDBSettings)
        assert isinstance(settings.document_db, DocumentDBSettings)
        assert isinstance(settings.transcription, TranscriptionSettings)
        assert isinstance(settings.embeddings, EmbeddingsSettings)
        assert isinstance(settings.llm, LLMSettings)
        assert isinstance(settings.chunking, ChunkingSettings)
        assert isinstance(settings.processing, ProcessingSettings)
        assert isinstance(settings.telemetry, TelemetrySettings)
        assert isinstance(settings.rate_limiting, RateLimitSettings)


class TestSettingsLoader:
    """Tests for SettingsLoader."""

    def test_load_empty_config(self):
        with TemporaryDirectory() as tmpdir:
            loader = SettingsLoader(config_dir=Path(tmpdir), environment="dev")
            settings = loader.load()
            assert settings.app.name == "youtube-rag-server"

    def test_load_base_config(self):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)
            base_config = {
                "app": {"name": "test-app", "environment": "dev"},
                "server": {"port": 9000},
            }
            with (config_dir / "appsettings.json").open("w") as f:
                json.dump(base_config, f)

            loader = SettingsLoader(config_dir=config_dir, environment="dev")
            settings = loader.load()
            assert settings.app.name == "test-app"
            assert settings.server.port == 9000

    def test_load_environment_override(self):
        with TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir)

            base_config = {
                "app": {"name": "test-app", "debug": False},
                "server": {"port": 8000, "workers": 1},
            }
            with (config_dir / "appsettings.json").open("w") as f:
                json.dump(base_config, f)

            prod_config = {
                "app": {"debug": False, "log_level": "WARNING"},
                "server": {"workers": 4, "docs_enabled": False},
            }
            with (config_dir / "appsettings.prod.json").open("w") as f:
                json.dump(prod_config, f)

            loader = SettingsLoader(config_dir=config_dir, environment="prod")
            settings = loader.load()

            # Base values
            assert settings.app.name == "test-app"
            assert settings.server.port == 8000
            # Overridden values
            assert settings.app.log_level == "WARNING"
            assert settings.server.workers == 4
            assert settings.server.docs_enabled is False

    def test_deep_merge(self):
        loader = SettingsLoader()
        base = {"a": {"b": 1, "c": 2}, "d": 3}
        override = {"a": {"b": 10, "e": 4}, "f": 5}

        result = loader._deep_merge(base, override)

        assert result == {"a": {"b": 10, "c": 2, "e": 4}, "d": 3, "f": 5}


class TestGetSettings:
    """Tests for get_settings function."""

    def setup_method(self):
        reset_settings()

    def teardown_method(self):
        reset_settings()
        # Clean up env vars
        for key in list(os.environ.keys()):
            if key.startswith("YOUTUBE_RAG__"):
                del os.environ[key]

    def test_get_settings_cached(self):
        with TemporaryDirectory() as tmpdir:
            settings1 = get_settings(config_dir=Path(tmpdir))
            settings2 = get_settings(config_dir=Path(tmpdir))
            assert settings1 is settings2

    def test_get_settings_reload(self):
        with TemporaryDirectory() as tmpdir:
            settings1 = get_settings(config_dir=Path(tmpdir))
            settings2 = get_settings(config_dir=Path(tmpdir), reload=True)
            assert settings1 is not settings2

    def test_reset_settings(self):
        with TemporaryDirectory() as tmpdir:
            settings1 = get_settings(config_dir=Path(tmpdir))
            reset_settings()
            settings2 = get_settings(config_dir=Path(tmpdir))
            assert settings1 is not settings2
