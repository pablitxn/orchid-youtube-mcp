"""Video storage service for managing blobs and metadata."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.commons.infrastructure.blob.base import BlobStorageBase
from src.commons.infrastructure.documentdb.base import DocumentDBBase
from src.commons.settings.models import BlobStorageSettings, DocumentDBSettings
from src.commons.telemetry import get_logger
from src.domain.models.chunk import (
    AnyChunk,
    AudioChunk,
    FrameChunk,
    Modality,
    TranscriptChunk,
    VideoChunk,
)
from src.domain.models.video import VideoMetadata, VideoStatus


class VideoStorageService:
    """Manages storage of video content and metadata.

    Handles:
    - Video/audio file storage in blob storage
    - Frame storage and thumbnail generation
    - Chunk metadata in document database
    - Video metadata CRUD operations
    """

    def __init__(
        self,
        blob_storage: BlobStorageBase,
        document_db: DocumentDBBase,
        blob_settings: BlobStorageSettings,
        doc_settings: DocumentDBSettings,
    ) -> None:
        """Initialize storage service.

        Args:
            blob_storage: Blob storage provider.
            document_db: Document database provider.
            blob_settings: Blob storage configuration.
            doc_settings: Document database configuration.
        """
        self._blob = blob_storage
        self._doc_db = document_db
        self._logger = get_logger(__name__)

        # Bucket names
        self._videos_bucket = blob_settings.buckets.videos
        self._frames_bucket = blob_settings.buckets.frames
        self._chunks_bucket = blob_settings.buckets.chunks
        self._presigned_expiry = blob_settings.presigned_url_expiry_seconds

        # Collection names
        self._videos_collection = doc_settings.collections.videos
        self._transcript_chunks_collection = doc_settings.collections.transcript_chunks
        self._frame_chunks_collection = doc_settings.collections.frame_chunks
        self._audio_chunks_collection = doc_settings.collections.audio_chunks
        self._video_chunks_collection = doc_settings.collections.video_chunks

    # =========================================================================
    # Bucket management
    # =========================================================================

    async def ensure_buckets_exist(self) -> None:
        """Ensure all required buckets exist."""
        buckets = [self._videos_bucket, self._frames_bucket, self._chunks_bucket]
        self._logger.debug(
            "Ensuring required buckets exist",
            extra={"buckets": buckets},
        )
        created = 0
        for bucket in buckets:
            if not await self._blob.bucket_exists(bucket):
                await self._blob.create_bucket(bucket)
                created += 1
                self._logger.debug(f"Created bucket: {bucket}")
        if created > 0:
            self._logger.info(
                "Buckets initialized",
                extra={"created": created, "total": len(buckets)},
            )

    # =========================================================================
    # Video metadata operations
    # =========================================================================

    async def save_video_metadata(self, video: VideoMetadata) -> str:
        """Save video metadata to document database.

        Args:
            video: Video metadata to save.

        Returns:
            Document ID.
        """
        self._logger.debug(
            "Saving video metadata",
            extra={
                "video_id": video.id,
                "youtube_id": video.youtube_id,
                "title": video.title,
                "status": video.status.value,
            },
        )
        doc_id = await self._doc_db.insert(
            self._videos_collection,
            video.model_dump(mode="json"),
        )
        self._logger.info(
            "Video metadata saved",
            extra={"video_id": video.id, "doc_id": doc_id},
        )
        return doc_id

    async def update_video_metadata(self, video: VideoMetadata) -> bool:
        """Update existing video metadata.

        Args:
            video: Updated video metadata.

        Returns:
            True if updated, False if not found.
        """
        self._logger.debug(
            "Updating video metadata",
            extra={
                "video_id": video.id,
                "status": video.status.value,
            },
        )
        result = await self._doc_db.update(
            self._videos_collection,
            video.id,
            video.model_dump(mode="json"),
        )
        if result:
            self._logger.debug("Video metadata updated", extra={"video_id": video.id})
        else:
            self._logger.warning(
                "Video metadata not found for update",
                extra={"video_id": video.id},
            )
        return result

    async def get_video_metadata(self, video_id: str) -> VideoMetadata | None:
        """Get video metadata by ID.

        Args:
            video_id: Internal video UUID.

        Returns:
            Video metadata or None if not found.
        """
        self._logger.debug("Fetching video metadata", extra={"video_id": video_id})
        doc = await self._doc_db.find_by_id(self._videos_collection, video_id)
        if not doc:
            self._logger.debug("Video metadata not found", extra={"video_id": video_id})
            return None
        self._logger.debug(
            "Video metadata found",
            extra={"video_id": video_id, "status": doc.get("status")},
        )
        return VideoMetadata(**doc)

    async def get_video_by_youtube_id(self, youtube_id: str) -> VideoMetadata | None:
        """Get video metadata by YouTube video ID.

        Args:
            youtube_id: YouTube video ID (11 characters).

        Returns:
            Video metadata or None if not found.
        """
        self._logger.debug(
            "Fetching video by YouTube ID",
            extra={"youtube_id": youtube_id},
        )
        doc = await self._doc_db.find_one(
            self._videos_collection,
            {"youtube_id": youtube_id},
        )
        if not doc:
            self._logger.debug(
                "Video not found by YouTube ID",
                extra={"youtube_id": youtube_id},
            )
            return None
        self._logger.debug(
            "Video found by YouTube ID",
            extra={"youtube_id": youtube_id, "video_id": doc.get("id")},
        )
        return VideoMetadata(**doc)

    async def list_videos(
        self,
        status: VideoStatus | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> list[VideoMetadata]:
        """List videos with optional filtering.

        Args:
            status: Optional status filter.
            skip: Number to skip.
            limit: Maximum to return.

        Returns:
            List of video metadata.
        """
        self._logger.debug(
            "Listing videos",
            extra={
                "status_filter": status.value if status else None,
                "skip": skip,
                "limit": limit,
            },
        )

        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status.value

        docs = await self._doc_db.find(
            self._videos_collection,
            filters,
            skip=skip,
            limit=limit,
            sort=[("created_at", -1)],
        )

        self._logger.debug(
            "Videos listed",
            extra={"count": len(docs)},
        )

        return [VideoMetadata(**doc) for doc in docs]

    async def delete_video_metadata(self, video_id: str) -> bool:
        """Delete video metadata.

        Args:
            video_id: Internal video UUID.

        Returns:
            True if deleted, False if not found.
        """
        self._logger.debug(
            "Deleting video metadata",
            extra={"video_id": video_id},
        )
        result = await self._doc_db.delete(self._videos_collection, video_id)
        if result:
            self._logger.info(
                "Video metadata deleted",
                extra={"video_id": video_id},
            )
        else:
            self._logger.warning(
                "Video metadata not found for deletion",
                extra={"video_id": video_id},
            )
        return result

    async def update_video_status(
        self,
        video_id: str,
        status: VideoStatus,
        error_message: str | None = None,
    ) -> bool:
        """Update video processing status.

        Args:
            video_id: Internal video UUID.
            status: New status.
            error_message: Optional error message for FAILED status.

        Returns:
            True if updated.
        """
        self._logger.debug(
            "Updating video status",
            extra={
                "video_id": video_id,
                "new_status": status.value,
                "has_error": error_message is not None,
            },
        )

        updates: dict[str, Any] = {
            "status": status.value,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        if error_message:
            updates["error_message"] = error_message

        result = await self._doc_db.update(self._videos_collection, video_id, updates)

        if result:
            self._logger.info(
                "Video status updated",
                extra={"video_id": video_id, "status": status.value},
            )
        return result

    # =========================================================================
    # Blob storage operations
    # =========================================================================

    async def upload_video(
        self,
        video_id: str,
        video_path: Path,
        content_type: str = "video/mp4",
    ) -> str:
        """Upload video file to blob storage.

        Args:
            video_id: Internal video UUID.
            video_path: Local path to video file.
            content_type: MIME type.

        Returns:
            Blob path.
        """
        blob_path = f"{video_id}/video{video_path.suffix}"
        file_size_mb = video_path.stat().st_size / (1024 * 1024)

        self._logger.debug(
            "Uploading video to blob storage",
            extra={
                "video_id": video_id,
                "blob_path": blob_path,
                "size_mb": round(file_size_mb, 2),
                "bucket": self._videos_bucket,
            },
        )

        with video_path.open("rb") as f:
            await self._blob.upload(
                self._videos_bucket,
                blob_path,
                f.read(),
                content_type=content_type,
            )

        self._logger.info(
            "Video uploaded to blob storage",
            extra={"video_id": video_id, "blob_path": blob_path},
        )
        return blob_path

    async def upload_audio(
        self,
        video_id: str,
        audio_path: Path,
        content_type: str = "audio/mpeg",
    ) -> str:
        """Upload audio file to blob storage.

        Args:
            video_id: Internal video UUID.
            audio_path: Local path to audio file.
            content_type: MIME type.

        Returns:
            Blob path.
        """
        blob_path = f"{video_id}/audio{audio_path.suffix}"
        file_size_mb = audio_path.stat().st_size / (1024 * 1024)

        self._logger.debug(
            "Uploading audio to blob storage",
            extra={
                "video_id": video_id,
                "blob_path": blob_path,
                "size_mb": round(file_size_mb, 2),
                "bucket": self._videos_bucket,
            },
        )

        with audio_path.open("rb") as f:
            await self._blob.upload(
                self._videos_bucket,
                blob_path,
                f.read(),
                content_type=content_type,
            )

        self._logger.info(
            "Audio uploaded to blob storage",
            extra={"video_id": video_id, "blob_path": blob_path},
        )
        return blob_path

    async def upload_frame(
        self,
        video_id: str,
        frame_path: Path,
        frame_number: int,
    ) -> tuple[str, str]:
        """Upload frame image to blob storage.

        Args:
            video_id: Internal video UUID.
            frame_path: Local path to frame image.
            frame_number: Frame sequence number.

        Returns:
            Tuple of (blob_path, thumbnail_path).
        """
        blob_path = f"{video_id}/frames/frame_{frame_number:05d}.jpg"
        thumb_path = f"{video_id}/frames/thumb_{frame_number:05d}.jpg"

        self._logger.debug(
            "Uploading frame to blob storage",
            extra={
                "video_id": video_id,
                "frame_number": frame_number,
                "blob_path": blob_path,
            },
        )

        with frame_path.open("rb") as f:
            frame_bytes = f.read()
            await self._blob.upload(
                self._frames_bucket,
                blob_path,
                frame_bytes,
                content_type="image/jpeg",
            )
            # Use same image as thumbnail for simplicity
            await self._blob.upload(
                self._frames_bucket,
                thumb_path,
                frame_bytes,
                content_type="image/jpeg",
            )

        return blob_path, thumb_path

    async def get_presigned_url(
        self,
        bucket: str,
        path: str,
        expiry_seconds: int | None = None,
    ) -> str:
        """Generate a presigned URL for blob access.

        Args:
            bucket: Bucket name.
            path: Blob path.
            expiry_seconds: URL validity duration.

        Returns:
            Presigned URL string.
        """
        expiry = expiry_seconds or self._presigned_expiry
        self._logger.debug(
            "Generating presigned URL",
            extra={
                "bucket": bucket,
                "path": path,
                "expiry_seconds": expiry,
            },
        )
        return await self._blob.generate_presigned_url(
            bucket,
            path,
            expiry,
        )

    async def delete_video_blobs(self, video_id: str) -> int:
        """Delete all blobs for a video.

        Args:
            video_id: Internal video UUID.

        Returns:
            Number of blobs deleted.
        """
        self._logger.info(
            "Deleting video blobs",
            extra={"video_id": video_id},
        )

        deleted = 0

        # Delete from videos bucket
        self._logger.debug(
            "Deleting from videos bucket",
            extra={"bucket": self._videos_bucket},
        )
        video_blobs = await self._blob.list_blobs(
            self._videos_bucket,
            prefix=f"{video_id}/",
        )
        for blob in video_blobs:
            if await self._blob.delete(self._videos_bucket, blob.path):
                deleted += 1

        # Delete from frames bucket
        self._logger.debug(
            "Deleting from frames bucket",
            extra={"bucket": self._frames_bucket},
        )
        frame_blobs = await self._blob.list_blobs(
            self._frames_bucket,
            prefix=f"{video_id}/",
        )
        for blob in frame_blobs:
            if await self._blob.delete(self._frames_bucket, blob.path):
                deleted += 1

        # Delete from chunks bucket
        self._logger.debug(
            "Deleting from chunks bucket",
            extra={"bucket": self._chunks_bucket},
        )
        chunk_blobs = await self._blob.list_blobs(
            self._chunks_bucket,
            prefix=f"{video_id}/",
        )
        for blob in chunk_blobs:
            if await self._blob.delete(self._chunks_bucket, blob.path):
                deleted += 1

        self._logger.info(
            "Video blobs deleted",
            extra={"video_id": video_id, "deleted_count": deleted},
        )

        return deleted

    # =========================================================================
    # Chunk storage operations
    # =========================================================================

    def _get_chunk_collection(self, modality: Modality) -> str:
        """Get collection name for chunk modality."""
        mapping = {
            Modality.TRANSCRIPT: self._transcript_chunks_collection,
            Modality.FRAME: self._frame_chunks_collection,
            Modality.AUDIO: self._audio_chunks_collection,
            Modality.VIDEO: self._video_chunks_collection,
        }
        return mapping[modality]

    async def save_chunks(self, chunks: list[AnyChunk]) -> list[str]:
        """Save chunks to document database.

        Args:
            chunks: Chunks to save.

        Returns:
            List of document IDs.
        """
        if not chunks:
            self._logger.debug("No chunks to save")
            return []

        self._logger.debug(
            "Saving chunks to document database",
            extra={"total_chunks": len(chunks)},
        )

        # Group by modality for batch insert
        by_modality: dict[Modality, list[AnyChunk]] = {}
        for chunk in chunks:
            if chunk.modality not in by_modality:
                by_modality[chunk.modality] = []
            by_modality[chunk.modality].append(chunk)

        all_ids: list[str] = []
        for modality, modality_chunks in by_modality.items():
            collection = self._get_chunk_collection(modality)
            docs = [c.model_dump(mode="json") for c in modality_chunks]

            self._logger.debug(
                f"Inserting {modality.value} chunks",
                extra={
                    "modality": modality.value,
                    "count": len(docs),
                    "collection": collection,
                },
            )

            ids = await self._doc_db.insert_many(collection, docs)
            all_ids.extend(ids)

        self._logger.info(
            "Chunks saved",
            extra={
                "total_saved": len(all_ids),
                "modalities": {m.value: len(c) for m, c in by_modality.items()},
            },
        )

        return all_ids

    async def get_chunks_for_video(
        self,
        video_id: str,
        modality: Modality | None = None,
    ) -> list[AnyChunk]:
        """Get all chunks for a video.

        Args:
            video_id: Internal video UUID.
            modality: Optional modality filter.

        Returns:
            List of chunks.
        """
        modalities = [modality] if modality else list(Modality)

        self._logger.debug(
            "Fetching chunks for video",
            extra={
                "video_id": video_id,
                "modality_filter": modality.value if modality else "all",
            },
        )

        chunks: list[AnyChunk] = []

        for mod in modalities:
            collection = self._get_chunk_collection(mod)
            docs = await self._doc_db.find(
                collection,
                {"video_id": video_id},
                limit=10000,
                sort=[("start_time", 1)],
            )

            for doc in docs:
                chunk = self._doc_to_chunk(doc, mod)
                if chunk:
                    chunks.append(chunk)

        self._logger.debug(
            "Chunks fetched for video",
            extra={
                "video_id": video_id,
                "total_chunks": len(chunks),
            },
        )

        return chunks

    def _doc_to_chunk(
        self,
        doc: dict[str, Any],
        modality: Modality,
    ) -> AnyChunk | None:
        """Convert document to appropriate chunk type."""
        if modality == Modality.TRANSCRIPT:
            return TranscriptChunk(**doc)
        elif modality == Modality.FRAME:
            return FrameChunk(**doc)
        elif modality == Modality.AUDIO:
            return AudioChunk(**doc)
        elif modality == Modality.VIDEO:
            return VideoChunk(**doc)
        return None

    async def delete_chunks_for_video(self, video_id: str) -> int:
        """Delete all chunks for a video.

        Args:
            video_id: Internal video UUID.

        Returns:
            Number of chunks deleted.
        """
        self._logger.info(
            "Deleting chunks for video",
            extra={"video_id": video_id},
        )

        deleted = 0
        deleted_by_modality: dict[str, int] = {}

        for modality in Modality:
            collection = self._get_chunk_collection(modality)
            count = await self._doc_db.delete_many(
                collection,
                {"video_id": video_id},
            )
            deleted += count
            deleted_by_modality[modality.value] = count

        self._logger.info(
            "Chunks deleted for video",
            extra={
                "video_id": video_id,
                "total_deleted": deleted,
                "by_modality": deleted_by_modality,
            },
        )

        return deleted

    async def get_chunk_by_id(
        self,
        chunk_id: str,
        modality: Modality,
    ) -> AnyChunk | None:
        """Get a specific chunk by ID.

        Args:
            chunk_id: Chunk UUID.
            modality: Chunk modality.

        Returns:
            Chunk or None if not found.
        """
        self._logger.debug(
            "Fetching chunk by ID",
            extra={
                "chunk_id": chunk_id,
                "modality": modality.value,
            },
        )

        collection = self._get_chunk_collection(modality)
        doc = await self._doc_db.find_by_id(collection, chunk_id)

        if not doc:
            self._logger.debug(
                "Chunk not found",
                extra={"chunk_id": chunk_id},
            )
            return None

        self._logger.debug(
            "Chunk found",
            extra={
                "chunk_id": chunk_id,
                "video_id": doc.get("video_id"),
            },
        )
        return self._doc_to_chunk(doc, modality)

    # =========================================================================
    # Full video deletion
    # =========================================================================

    async def delete_video_completely(self, video_id: str) -> dict[str, int]:
        """Delete a video and all associated data.

        Args:
            video_id: Internal video UUID.

        Returns:
            Dictionary with deletion counts.
        """
        self._logger.info(
            "Starting complete video deletion",
            extra={"video_id": video_id},
        )

        self._logger.debug("Deleting video blobs")
        blobs_deleted = await self.delete_video_blobs(video_id)

        self._logger.debug("Deleting video chunks")
        chunks_deleted = await self.delete_chunks_for_video(video_id)

        self._logger.debug("Deleting video metadata")
        metadata_deleted = 1 if await self.delete_video_metadata(video_id) else 0

        results = {
            "blobs": blobs_deleted,
            "chunks": chunks_deleted,
            "metadata": metadata_deleted,
        }

        self._logger.info(
            "Complete video deletion finished",
            extra={
                "video_id": video_id,
                "blobs_deleted": blobs_deleted,
                "chunks_deleted": chunks_deleted,
                "metadata_deleted": metadata_deleted,
            },
        )

        return results
