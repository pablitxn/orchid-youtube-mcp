#!/usr/bin/env python3
"""
Development script to clean all databases (MinIO, Qdrant, MongoDB).

WARNING: This script will delete ALL data from the databases.
Only use in development environments!

Usage:
    python scripts/clean_databases.py [--all | --minio | --qdrant | --mongodb]

Options:
    --all       Clean all databases (default)
    --minio     Clean only MinIO buckets
    --qdrant    Clean only Qdrant collections
    --mongodb   Clean only MongoDB collections
    --dry-run   Show what would be deleted without actually deleting
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from minio import Minio
    from qdrant_client import QdrantClient


@dataclass
class MinioConfig:
    """MinIO configuration."""

    endpoint: str = field(
        default_factory=lambda: os.getenv("MINIO_ENDPOINT", "localhost:9000")
    )
    access_key: str = field(
        default_factory=lambda: os.getenv("MINIO_ROOT_USER", "")
    )
    secret_key: str = field(
        default_factory=lambda: os.getenv("MINIO_ROOT_PASSWORD", "")
    )
    secure: bool = False
    buckets: list[str] = field(
        default_factory=lambda: ["rag-videos", "rag-chunks", "rag-frames"]
    )


@dataclass
class QdrantConfig:
    """Qdrant configuration."""

    host: str = field(default_factory=lambda: os.getenv("QDRANT_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.getenv("QDRANT_PORT", "6333")))
    collections: list[str] = field(
        default_factory=lambda: [
            "transcript_embeddings",
            "frame_embeddings",
            "video_embeddings",
        ]
    )


@dataclass
class MongoDBConfig:
    """MongoDB configuration."""

    host: str = field(default_factory=lambda: os.getenv("MONGO_HOST", "localhost"))
    port: int = field(default_factory=lambda: int(os.getenv("MONGO_PORT", "27017")))
    username: str = field(default_factory=lambda: os.getenv("MONGO_USERNAME", ""))
    password: str = field(
        default_factory=lambda: os.getenv("MONGO_PASSWORD", "")
    )
    database: str = "youtube_rag"
    collections: list[str] = field(
        default_factory=lambda: [
            "videos",
            "transcript_chunks",
            "frame_chunks",
            "audio_chunks",
            "video_chunks",
            "citations",
        ]
    )


MINIO_CONFIG = MinioConfig()
QDRANT_CONFIG = QdrantConfig()
MONGODB_CONFIG = MongoDBConfig()


def clean_minio(dry_run: bool = False) -> None:
    """Clean all objects from MinIO buckets."""
    from minio import Minio
    from minio.error import S3Error

    print("\n=== Cleaning MinIO ===")

    client: Minio = Minio(
        MINIO_CONFIG.endpoint,
        access_key=MINIO_CONFIG.access_key,
        secret_key=MINIO_CONFIG.secret_key,
        secure=MINIO_CONFIG.secure,
    )

    for bucket_name in MINIO_CONFIG.buckets:
        try:
            _clean_minio_bucket(client, bucket_name, dry_run)
        except S3Error as e:
            print(f"  Error cleaning bucket '{bucket_name}': {e}")


def _clean_minio_bucket(client: Minio, bucket_name: str, dry_run: bool) -> None:
    """Clean a single MinIO bucket."""
    if not client.bucket_exists(bucket_name):
        print(f"  Bucket '{bucket_name}' does not exist, skipping...")
        return

    objects = list(client.list_objects(bucket_name, recursive=True))
    object_count = len(objects)

    if object_count == 0:
        print(f"  Bucket '{bucket_name}' is already empty")
        return

    if dry_run:
        print(f"  [DRY-RUN] Would delete {object_count} objects from '{bucket_name}'")
        return

    for obj in objects:
        client.remove_object(bucket_name, obj.object_name)

    print(f"  Deleted {object_count} objects from '{bucket_name}'")


def clean_qdrant(dry_run: bool = False) -> None:
    """Delete all Qdrant collections."""
    from qdrant_client import QdrantClient
    from qdrant_client.http.exceptions import UnexpectedResponse

    print("\n=== Cleaning Qdrant ===")

    client: QdrantClient = QdrantClient(
        host=QDRANT_CONFIG.host,
        port=QDRANT_CONFIG.port,
    )

    for collection_name in QDRANT_CONFIG.collections:
        try:
            _clean_qdrant_collection(client, collection_name, dry_run)
        except UnexpectedResponse as e:
            print(f"  Error cleaning collection '{collection_name}': {e}")


def _clean_qdrant_collection(
    client: QdrantClient, collection_name: str, dry_run: bool
) -> None:
    """Clean a single Qdrant collection."""
    collections = client.get_collections().collections
    collection_names = [c.name for c in collections]

    if collection_name not in collection_names:
        print(f"  Collection '{collection_name}' does not exist, skipping...")
        return

    collection_info = client.get_collection(collection_name)
    point_count = collection_info.points_count

    if dry_run:
        msg = f"  [DRY-RUN] Would delete collection '{collection_name}'"
        print(f"{msg} ({point_count} points)")
        return

    client.delete_collection(collection_name)
    print(f"  Deleted collection '{collection_name}' ({point_count} points)")


async def clean_mongodb_async(dry_run: bool = False) -> None:
    """Clean all documents from MongoDB collections."""
    from motor.motor_asyncio import AsyncIOMotorClient

    print("\n=== Cleaning MongoDB ===")

    connection_string = (
        f"mongodb://{MONGODB_CONFIG.username}:{MONGODB_CONFIG.password}"
        f"@{MONGODB_CONFIG.host}:{MONGODB_CONFIG.port}"
        f"/?authSource=admin"
    )

    client: AsyncIOMotorClient[dict[str, Any]] = AsyncIOMotorClient(connection_string)
    db = client[MONGODB_CONFIG.database]

    try:
        for collection_name in MONGODB_CONFIG.collections:
            await _clean_mongodb_collection(db, collection_name, dry_run)
    finally:
        client.close()


async def _clean_mongodb_collection(
    db: Any, collection_name: str, dry_run: bool
) -> None:
    """Clean a single MongoDB collection."""
    collection = db[collection_name]
    doc_count: int = await collection.count_documents({})

    if doc_count == 0:
        print(f"  Collection '{collection_name}' is already empty")
        return

    if dry_run:
        msg = f"  [DRY-RUN] Would delete {doc_count} documents"
        print(f"{msg} from '{collection_name}'")
        return

    result = await collection.delete_many({})
    print(f"  Deleted {result.deleted_count} documents from '{collection_name}'")


def clean_mongodb(dry_run: bool = False) -> None:
    """Wrapper to run async MongoDB cleanup."""
    asyncio.run(clean_mongodb_async(dry_run))


@dataclass
class CleanupArgs:
    """Parsed command line arguments."""

    clean_minio: bool
    clean_qdrant: bool
    clean_mongodb: bool
    dry_run: bool
    skip_confirm: bool


def parse_args() -> CleanupArgs:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Clean development databases (MinIO, Qdrant, MongoDB)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--all",
        action="store_true",
        default=False,
        help="Clean all databases (default if no option specified)",
    )
    parser.add_argument("--minio", action="store_true", help="Clean only MinIO buckets")
    parser.add_argument(
        "--qdrant", action="store_true", help="Clean only Qdrant collections"
    )
    parser.add_argument(
        "--mongodb", action="store_true", help="Clean only MongoDB collections"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting",
    )
    parser.add_argument(
        "-y", "--yes", action="store_true", help="Skip confirmation prompt"
    )

    args = parser.parse_args()
    clean_all = args.all or not (args.minio or args.qdrant or args.mongodb)

    return CleanupArgs(
        clean_minio=clean_all or args.minio,
        clean_qdrant=clean_all or args.qdrant,
        clean_mongodb=clean_all or args.mongodb,
        dry_run=args.dry_run,
        skip_confirm=args.yes,
    )


def run_cleanup(args: CleanupArgs) -> list[str]:
    """Execute cleanup operations and return list of errors."""
    errors: list[str] = []
    cleaners: list[tuple[bool, str, Callable[[bool], None]]] = [
        (args.clean_minio, "MinIO", clean_minio),
        (args.clean_qdrant, "Qdrant", clean_qdrant),
        (args.clean_mongodb, "MongoDB", clean_mongodb),
    ]

    for should_clean, name, cleaner in cleaners:
        if should_clean:
            try:
                cleaner(args.dry_run)
            except Exception as e:
                errors.append(f"{name}: {e}")
                print(f"  Failed to connect to {name}: {e}")

    return errors


def main() -> None:
    """Main entry point."""
    args = parse_args()

    targets = []
    if args.clean_minio:
        targets.append("MinIO")
    if args.clean_qdrant:
        targets.append("Qdrant")
    if args.clean_mongodb:
        targets.append("MongoDB")

    print("=" * 50)
    print("  DATABASE CLEANUP SCRIPT - DEVELOPMENT ONLY")
    print("=" * 50)
    print(f"\nTargets: {', '.join(targets)}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'DESTRUCTIVE'}")

    if not args.skip_confirm and not args.dry_run:
        response = input("\nAre you sure you want to continue? [y/N]: ")
        if response.lower() not in ("y", "yes"):
            print("Aborted.")
            sys.exit(0)

    errors = run_cleanup(args)

    print("\n" + "=" * 50)
    if errors:
        print(f"Completed with {len(errors)} error(s):")
        for error in errors:
            print(f"  - {error}")
        sys.exit(1)
    print("Cleanup completed successfully!")
    print("=" * 50)


if __name__ == "__main__":
    main()
