"""Shared fixtures for integration tests against local docker-compose services."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import pytest_asyncio
from minio import Minio
from motor.motor_asyncio import AsyncIOMotorClient
from qdrant_client import AsyncQdrantClient

from src.commons.runtime import load_shared_app_settings
from src.commons.settings.loader import get_settings, reset_settings


@dataclass(slots=True)
class IntegrationServiceConfig:
    """Resolved integration service connection settings."""

    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_secure: bool
    minio_buckets: dict[str, str]

    qdrant_url: str | None
    qdrant_host: str | None
    qdrant_port: int
    qdrant_grpc_port: int
    qdrant_use_ssl: bool
    qdrant_api_key: str | None

    mongodb_database: str
    mongodb_uri_candidates: tuple[str, ...]
    mongodb_uri: str | None = None


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _with_mongo_auth(
    uri: str,
    *,
    username: str,
    password: str,
    auth_source: str,
) -> str:
    parts = urlsplit(uri)
    if parts.scheme not in {"mongodb", "mongodb+srv"}:
        return uri
    if "@" in parts.netloc:
        return uri

    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.setdefault("authSource", auth_source)
    netloc = f"{username}:{password}@{parts.netloc}"
    return urlunsplit(
        (
            parts.scheme,
            netloc,
            parts.path,
            urlencode(query),
            parts.fragment,
        )
    )


def _build_config_from_appsettings() -> IntegrationServiceConfig:
    reset_settings()
    app_settings = get_settings(
        config_dir=Path("config"),
        environment="dev",
        reload=True,
    )
    shared_settings = load_shared_app_settings(app_settings.app.environment)
    resources = shared_settings.resources

    if (
        resources.multi_bucket is None
        or resources.mongodb is None
        or resources.qdrant is None
    ):
        pytest.skip(
            "Missing shared resources configuration for integration tests "
            "(requires multi_bucket, mongodb and qdrant)."
        )

    minio_endpoint = os.getenv(
        "YOUTUBE_MCP_IT_MINIO_ENDPOINT",
        resources.multi_bucket.endpoint,
    )
    minio_access_key = os.getenv(
        "YOUTUBE_MCP_IT_MINIO_ACCESS_KEY",
        resources.multi_bucket.access_key,
    )
    minio_secret_key = os.getenv(
        "YOUTUBE_MCP_IT_MINIO_SECRET_KEY",
        resources.multi_bucket.secret_key,
    )
    minio_secure = _env_bool(
        "YOUTUBE_MCP_IT_MINIO_SECURE",
        resources.multi_bucket.secure,
    )

    qdrant_url = os.getenv("YOUTUBE_MCP_IT_QDRANT_URL", resources.qdrant.url or "")
    qdrant_host = os.getenv("YOUTUBE_MCP_IT_QDRANT_HOST", resources.qdrant.host or "")

    raw_mongodb_uri = os.getenv("YOUTUBE_MCP_IT_MONGODB_URI", resources.mongodb.uri)
    mongodb_uri_candidates = [raw_mongodb_uri]
    if "@" not in raw_mongodb_uri:
        mongodb_uri_candidates.insert(
            0,
            _with_mongo_auth(
                raw_mongodb_uri,
                username=os.getenv("YOUTUBE_MCP_IT_MONGODB_USER", "admin"),
                password=os.getenv("YOUTUBE_MCP_IT_MONGODB_PASSWORD", "password"),
                auth_source=os.getenv("YOUTUBE_MCP_IT_MONGODB_AUTH_SOURCE", "admin"),
            ),
        )

    return IntegrationServiceConfig(
        minio_endpoint=minio_endpoint,
        minio_access_key=minio_access_key,
        minio_secret_key=minio_secret_key,
        minio_secure=minio_secure,
        minio_buckets=dict(resources.multi_bucket.buckets),
        qdrant_url=qdrant_url or None,
        qdrant_host=qdrant_host or None,
        qdrant_port=int(
            os.getenv("YOUTUBE_MCP_IT_QDRANT_PORT", str(resources.qdrant.port))
        ),
        qdrant_grpc_port=int(
            os.getenv(
                "YOUTUBE_MCP_IT_QDRANT_GRPC_PORT",
                str(resources.qdrant.grpc_port),
            )
        ),
        qdrant_use_ssl=_env_bool(
            "YOUTUBE_MCP_IT_QDRANT_USE_SSL",
            resources.qdrant.use_ssl,
        ),
        qdrant_api_key=os.getenv(
            "YOUTUBE_MCP_IT_QDRANT_API_KEY",
            resources.qdrant.api_key,
        ),
        mongodb_database=os.getenv(
            "YOUTUBE_MCP_IT_MONGODB_DATABASE",
            resources.mongodb.database,
        ),
        mongodb_uri_candidates=tuple(dict.fromkeys(mongodb_uri_candidates)),
    )


async def _check_minio(config: IntegrationServiceConfig) -> None:
    client = Minio(
        endpoint=config.minio_endpoint,
        access_key=config.minio_access_key,
        secret_key=config.minio_secret_key,
        secure=config.minio_secure,
    )
    await asyncio.to_thread(client.list_buckets)


async def _check_qdrant(config: IntegrationServiceConfig) -> None:
    if config.qdrant_url is not None:
        client = AsyncQdrantClient(
            url=config.qdrant_url,
            api_key=config.qdrant_api_key,
            prefer_grpc=False,
        )
    else:
        client = AsyncQdrantClient(
            host=config.qdrant_host,
            port=config.qdrant_port,
            grpc_port=config.qdrant_grpc_port,
            https=config.qdrant_use_ssl,
            api_key=config.qdrant_api_key,
            prefer_grpc=False,
        )

    try:
        await client.get_collections()
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            await close()


async def _resolve_working_mongodb_uri(
    candidates: tuple[str, ...],
    *,
    database_name: str,
) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    for uri in candidates:
        client = AsyncIOMotorClient(
            uri,
            serverSelectionTimeoutMS=1500,
            connectTimeoutMS=1500,
        )
        try:
            await client.admin.command("ping")
            probe_collection = client[database_name][f"auth_probe_{os.getpid()}"]
            probe_result = await probe_collection.insert_one({"probe": True})
            await probe_collection.delete_one({"_id": probe_result.inserted_id})
            return uri, errors
        except Exception as exc:
            errors.append(f"{uri} ({type(exc).__name__}: {exc})")
        finally:
            client.close()
    return None, errors


@pytest.fixture(scope="session")
def integration_service_config() -> IntegrationServiceConfig:
    """Resolve service settings from appsettings + optional env overrides."""
    return _build_config_from_appsettings()


@pytest_asyncio.fixture
async def require_integration_services(
    integration_service_config: IntegrationServiceConfig,
) -> IntegrationServiceConfig:
    """Skip integration tests cleanly if required services are not available."""
    config = integration_service_config
    failures: list[str] = []

    try:
        await _check_minio(config)
    except Exception as exc:
        failures.append(
            f"minio({config.minio_endpoint}) -> {type(exc).__name__}: {exc}"
        )

    mongodb_uri, mongodb_errors = await _resolve_working_mongodb_uri(
        config.mongodb_uri_candidates,
        database_name=config.mongodb_database,
    )
    if mongodb_uri is None:
        if mongodb_errors:
            failures.append("mongodb -> " + " | ".join(mongodb_errors))
        else:
            failures.append("mongodb -> no URI candidates configured")
    else:
        config = replace(config, mongodb_uri=mongodb_uri)

    try:
        await _check_qdrant(config)
    except Exception as exc:
        endpoint = config.qdrant_url or f"{config.qdrant_host}:{config.qdrant_port}"
        failures.append(f"qdrant({endpoint}) -> {type(exc).__name__}: {exc}")

    if failures:
        details = "; ".join(failures)
        pytest.skip(
            "Integration services unavailable. Start local dependencies with "
            "`docker compose up -d minio qdrant mongodb`. "
            f"Details: {details}"
        )

    return config


@pytest.fixture
def integration_shared_app_settings(
    require_integration_services: IntegrationServiceConfig,
):
    """Return shared app settings with integration endpoint overrides applied."""
    app_settings = get_settings(
        config_dir=Path("config"),
        environment="dev",
        reload=True,
    )
    shared_settings = load_shared_app_settings(app_settings.app.environment)
    resources = shared_settings.resources

    if (
        resources.multi_bucket is None
        or resources.mongodb is None
        or resources.qdrant is None
    ):
        raise RuntimeError("Missing required shared resources in appsettings")

    config = require_integration_services
    mongodb_uri = config.mongodb_uri
    if mongodb_uri is None:
        raise RuntimeError("MongoDB URI was not resolved for integration test")

    multi_bucket = resources.multi_bucket.model_copy(
        update={
            "endpoint": config.minio_endpoint,
            "access_key": config.minio_access_key,
            "secret_key": config.minio_secret_key,
            "secure": config.minio_secure,
            "buckets": dict(config.minio_buckets),
        }
    )
    mongodb = resources.mongodb.model_copy(
        update={
            "uri": mongodb_uri,
            "database": config.mongodb_database,
        }
    )
    qdrant = resources.qdrant.model_copy(
        update={
            "url": config.qdrant_url,
            "host": config.qdrant_host,
            "port": config.qdrant_port,
            "grpc_port": config.qdrant_grpc_port,
            "use_ssl": config.qdrant_use_ssl,
            "api_key": config.qdrant_api_key,
        }
    )

    patched_resources = resources.model_copy(
        update={
            "multi_bucket": multi_bucket,
            "mongodb": mongodb,
            "qdrant": qdrant,
        }
    )
    patched_observability = shared_settings.observability.model_copy(
        update={"enabled": True}
    )
    return shared_settings.model_copy(
        update={
            "resources": patched_resources,
            "observability": patched_observability,
        }
    )
