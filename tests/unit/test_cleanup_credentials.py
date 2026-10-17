"""Cleanup must require private credentials before constructing service clients."""

import importlib.util
import secrets
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest


@pytest.fixture
def cleanup(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    for key in (
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "MONGO_USERNAME",
        "MONGO_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)
    path = Path(__file__).parents[2] / "scripts" / "clean_databases.py"
    spec = importlib.util.spec_from_file_location("cleanup_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "has_user,has_password", [(False, False), (True, False), (False, True)]
)
def test_minio_missing_credentials_fail_before_client(
    cleanup: ModuleType, has_user: bool, has_password: bool
) -> None:
    cleanup.MINIO_CONFIG.access_key = secrets.token_urlsafe(24) if has_user else ""
    cleanup.MINIO_CONFIG.secret_key = secrets.token_urlsafe(24) if has_password else ""
    with pytest.raises(ValueError, match="Set MINIO_ROOT_USER"):
        cleanup.clean_minio(dry_run=True)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "has_user,has_password", [(False, False), (True, False), (False, True)]
)
async def test_mongo_missing_credentials_fail_before_client(
    cleanup: ModuleType, has_user: bool, has_password: bool
) -> None:
    cleanup.MONGODB_CONFIG.username = secrets.token_urlsafe(24) if has_user else ""
    cleanup.MONGODB_CONFIG.password = secrets.token_urlsafe(24) if has_password else ""
    with pytest.raises(ValueError, match="Set MONGO_USERNAME"):
        await cleanup.clean_mongodb_async(dry_run=True)


def test_minio_private_credentials_preserve_client_arguments(
    cleanup: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    import minio

    access, secret = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    cleanup.MINIO_CONFIG.access_key, cleanup.MINIO_CONFIG.secret_key = access, secret
    client = MagicMock()
    client.bucket_exists.return_value = False
    constructor = Mock(return_value=client)
    monkeypatch.setattr(minio, "Minio", constructor)
    cleanup.clean_minio(dry_run=True)
    constructor.assert_called_once_with(
        cleanup.MINIO_CONFIG.endpoint,
        access_key=access,
        secret_key=secret,
        secure=cleanup.MINIO_CONFIG.secure,
    )
    client.remove_object.assert_not_called()


@pytest.mark.asyncio
async def test_mongo_private_credentials_preserve_client_arguments(
    cleanup: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    import motor.motor_asyncio

    username, password = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    cleanup.MONGODB_CONFIG.username, cleanup.MONGODB_CONFIG.password = (
        username,
        password,
    )
    client = MagicMock()
    client.__getitem__.return_value.__getitem__.return_value.count_documents = (
        AsyncMock(return_value=0)
    )
    constructor = Mock(return_value=client)
    monkeypatch.setattr(motor.motor_asyncio, "AsyncIOMotorClient", constructor)
    await cleanup.clean_mongodb_async(dry_run=True)
    uri = constructor.call_args.args[0]
    assert f"mongodb://{username}:{password}@" in uri
    client.close.assert_called_once_with()
