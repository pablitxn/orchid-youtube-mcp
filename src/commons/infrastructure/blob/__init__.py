"""Blob storage abstractions and implementations."""

from orchid_commons.blob import BlobNotFoundError

from src.commons.infrastructure.blob.base import (
    BlobMetadata,
    BlobStorageBase,
    HealthStatus,
)
from src.commons.infrastructure.blob.multi_bucket_adapter import (
    MultiBucketBlobStorageAdapter,
)

__all__ = [
    # Base classes
    "BlobMetadata",
    "BlobStorageBase",
    "HealthStatus",
    # Implementations
    "MultiBucketBlobStorageAdapter",
    # Exceptions
    "BlobNotFoundError",
]
