"""Document database abstractions and implementations."""

from src.commons.infrastructure.documentdb.base import DocumentDBBase
from src.commons.infrastructure.documentdb.mongodb_provider import MongoDBDocumentDB

__all__ = [
    # Base classes
    "DocumentDBBase",
    # Implementations
    "MongoDBDocumentDB",
]
