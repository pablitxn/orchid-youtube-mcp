"""Document database abstractions and implementations."""

from src.commons.infrastructure.documentdb.base import DocumentDBBase
from src.commons.infrastructure.documentdb.commons_adapter import (
    CommonsMongoDocumentDBAdapter,
)
from src.commons.infrastructure.documentdb.mongodb_provider import MongoDBDocumentDB

__all__ = [
    # Base classes
    "DocumentDBBase",
    # Adapters
    "CommonsMongoDocumentDBAdapter",
    # Implementations
    "MongoDBDocumentDB",
]
