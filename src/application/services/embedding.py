"""Embedding orchestration service for batch embedding generation."""

from dataclasses import dataclass

from src.commons.infrastructure.vectordb.base import VectorDBBase, VectorPoint
from src.commons.telemetry import get_logger
from src.domain.models.chunk import (
    AnyChunk,
    FrameChunk,
    Modality,
    TranscriptChunk,
)
from src.infrastructure.embeddings.base import EmbeddingServiceBase


@dataclass
class EmbeddingStats:
    """Statistics from embedding generation."""

    total_items: int
    text_embeddings: int
    image_embeddings: int
    vectors_stored: int
    failed_items: int


class EmbeddingOrchestrator:
    """Orchestrates embedding generation for different content types.

    Handles:
    - Batch text embedding generation
    - Batch image embedding generation
    - Vector storage with payloads
    - Error handling and retries
    """

    def __init__(
        self,
        text_embedder: EmbeddingServiceBase,
        image_embedder: EmbeddingServiceBase | None,
        vector_db: VectorDBBase,
        text_collection: str,
        image_collection: str | None = None,
    ) -> None:
        """Initialize embedding orchestrator.

        Args:
            text_embedder: Text embedding service.
            image_embedder: Optional image embedding service.
            vector_db: Vector database for storage.
            text_collection: Collection name for text embeddings.
            image_collection: Collection name for image embeddings.
        """
        self._text_embedder = text_embedder
        self._image_embedder = image_embedder
        self._vector_db = vector_db
        self._text_collection = text_collection
        self._image_collection = image_collection
        self._logger = get_logger(__name__)

    async def embed_transcript_chunks(
        self,
        chunks: list[TranscriptChunk],
        video_id: str,
    ) -> EmbeddingStats:
        """Generate and store embeddings for transcript chunks.

        Args:
            chunks: Transcript chunks to embed.
            video_id: Parent video ID.

        Returns:
            Statistics about the embedding operation.
        """
        self._logger.debug(
            "Starting transcript embedding",
            extra={
                "video_id": video_id,
                "chunk_count": len(chunks),
                "collection": self._text_collection,
                "embedding_dimensions": self._text_embedder.text_dimensions,
            },
        )

        if not chunks:
            self._logger.debug("No chunks provided, returning empty stats")
            return EmbeddingStats(
                total_items=0,
                text_embeddings=0,
                image_embeddings=0,
                vectors_stored=0,
                failed_items=0,
            )

        # Ensure collection exists
        self._logger.debug(
            "Ensuring vector collection exists",
            extra={"collection": self._text_collection},
        )
        await self._ensure_collection(
            self._text_collection,
            self._text_embedder.text_dimensions,
        )

        # Process in batches
        batch_size = self._text_embedder.max_batch_size
        total_batches = (len(chunks) + batch_size - 1) // batch_size
        all_vectors: list[VectorPoint] = []
        failed = 0

        self._logger.debug(
            "Processing embeddings in batches",
            extra={
                "batch_size": batch_size,
                "total_batches": total_batches,
            },
        )

        for i in range(0, len(chunks), batch_size):
            batch_num = i // batch_size + 1
            batch = chunks[i : i + batch_size]
            texts = [chunk.text for chunk in batch]

            try:
                self._logger.debug(
                    f"Processing batch {batch_num}/{total_batches}",
                    extra={"batch_size": len(batch)},
                )
                embeddings = await self._text_embedder.embed_texts(texts)

                for chunk, embedding in zip(batch, embeddings, strict=True):
                    point = VectorPoint(
                        id=chunk.id,
                        vector=embedding.vector,
                        payload={
                            "video_id": video_id,
                            "chunk_id": chunk.id,
                            "modality": Modality.TRANSCRIPT.value,
                            "start_time": chunk.start_time,
                            "end_time": chunk.end_time,
                            "text_preview": chunk.text[:200],
                            "language": chunk.language,
                            "confidence": chunk.confidence,
                        },
                    )
                    all_vectors.append(point)

            except Exception as e:
                failed += len(batch)
                self._logger.error(
                    f"Batch {batch_num} embedding failed",
                    extra={
                        "batch_num": batch_num,
                        "batch_size": len(batch),
                        "error": str(e),
                    },
                )

        # Store all vectors
        stored = 0
        if all_vectors:
            self._logger.debug(
                "Upserting vectors to database",
                extra={"vector_count": len(all_vectors)},
            )
            stored = await self._vector_db.upsert(self._text_collection, all_vectors)

        self._logger.info(
            "Transcript embedding completed",
            extra={
                "video_id": video_id,
                "total_chunks": len(chunks),
                "embeddings_generated": len(all_vectors),
                "vectors_stored": stored,
                "failed": failed,
            },
        )

        return EmbeddingStats(
            total_items=len(chunks),
            text_embeddings=len(all_vectors),
            image_embeddings=0,
            vectors_stored=stored,
            failed_items=failed,
        )

    async def embed_frame_chunks(
        self,
        chunks: list[FrameChunk],
        video_id: str,
    ) -> EmbeddingStats:
        """Generate and store embeddings for frame chunks.

        Uses image embeddings if available, otherwise falls back to
        text embeddings of frame descriptions.

        Args:
            chunks: Frame chunks to embed.
            video_id: Parent video ID.

        Returns:
            Statistics about the embedding operation.
        """
        self._logger.debug(
            "Starting frame embedding",
            extra={
                "video_id": video_id,
                "chunk_count": len(chunks),
                "has_image_embedder": self._image_embedder is not None,
                "image_collection": self._image_collection,
            },
        )

        if not chunks:
            self._logger.debug("No frame chunks provided, returning empty stats")
            return EmbeddingStats(
                total_items=0,
                text_embeddings=0,
                image_embeddings=0,
                vectors_stored=0,
                failed_items=0,
            )

        # Use image embedder if available
        if self._image_embedder and self._image_collection:
            self._logger.debug("Using image embedder for frames")
            return await self._embed_frames_as_images(chunks, video_id)

        # Fall back to text embeddings of descriptions
        self._logger.debug("Falling back to text embeddings for frame descriptions")
        return await self._embed_frames_as_text(chunks, video_id)

    async def _embed_frames_as_images(
        self,
        chunks: list[FrameChunk],
        video_id: str,
    ) -> EmbeddingStats:
        """Embed frames using image embeddings."""
        if not self._image_embedder or not self._image_collection:
            self._logger.warning(
                "Image embedder not configured, cannot embed frames as images",
                extra={"video_id": video_id, "chunk_count": len(chunks)},
            )
            return EmbeddingStats(
                total_items=len(chunks),
                text_embeddings=0,
                image_embeddings=0,
                vectors_stored=0,
                failed_items=len(chunks),
            )

        self._logger.debug(
            "Embedding frames as images",
            extra={
                "video_id": video_id,
                "chunk_count": len(chunks),
                "image_dimensions": self._image_embedder.image_dimensions,
            },
        )

        # Ensure collection exists
        if self._image_embedder.image_dimensions:
            await self._ensure_collection(
                self._image_collection,
                self._image_embedder.image_dimensions,
            )

        batch_size = self._image_embedder.max_batch_size
        total_batches = (len(chunks) + batch_size - 1) // batch_size
        all_vectors: list[VectorPoint] = []
        failed = 0

        for i in range(0, len(chunks), batch_size):
            batch_num = i // batch_size + 1
            batch = chunks[i : i + batch_size]
            image_paths = [chunk.blob_path for chunk in batch]

            try:
                self._logger.debug(
                    f"Processing image batch {batch_num}/{total_batches}",
                    extra={"batch_size": len(batch)},
                )
                embeddings = await self._image_embedder.embed_images(image_paths)

                for chunk, embedding in zip(batch, embeddings, strict=True):
                    point = VectorPoint(
                        id=chunk.id,
                        vector=embedding.vector,
                        payload={
                            "video_id": video_id,
                            "chunk_id": chunk.id,
                            "modality": Modality.FRAME.value,
                            "start_time": chunk.start_time,
                            "end_time": chunk.end_time,
                            "frame_number": chunk.frame_number,
                            "description": chunk.description or "",
                        },
                    )
                    all_vectors.append(point)

            except Exception as e:
                failed += len(batch)
                self._logger.error(
                    f"Image batch {batch_num} embedding failed",
                    extra={
                        "batch_num": batch_num,
                        "batch_size": len(batch),
                        "error": str(e),
                    },
                )

        stored = 0
        if all_vectors:
            stored = await self._vector_db.upsert(self._image_collection, all_vectors)

        self._logger.info(
            "Frame image embedding completed",
            extra={
                "video_id": video_id,
                "total_frames": len(chunks),
                "embeddings_generated": len(all_vectors),
                "vectors_stored": stored,
                "failed": failed,
            },
        )

        return EmbeddingStats(
            total_items=len(chunks),
            text_embeddings=0,
            image_embeddings=len(all_vectors),
            vectors_stored=stored,
            failed_items=failed,
        )

    async def _embed_frames_as_text(
        self,
        chunks: list[FrameChunk],
        video_id: str,
    ) -> EmbeddingStats:
        """Embed frame descriptions as text."""
        # Filter to chunks with descriptions
        chunks_with_desc = [c for c in chunks if c.description]

        self._logger.debug(
            "Embedding frame descriptions as text",
            extra={
                "video_id": video_id,
                "total_chunks": len(chunks),
                "chunks_with_descriptions": len(chunks_with_desc),
            },
        )

        if not chunks_with_desc:
            self._logger.debug(
                "No frames have descriptions, skipping text embedding",
                extra={"video_id": video_id},
            )
            return EmbeddingStats(
                total_items=len(chunks),
                text_embeddings=0,
                image_embeddings=0,
                vectors_stored=0,
                failed_items=0,
            )

        batch_size = self._text_embedder.max_batch_size
        total_batches = (len(chunks_with_desc) + batch_size - 1) // batch_size
        all_vectors: list[VectorPoint] = []
        failed = 0

        for i in range(0, len(chunks_with_desc), batch_size):
            batch_num = i // batch_size + 1
            batch = chunks_with_desc[i : i + batch_size]
            texts = [chunk.description for chunk in batch if chunk.description]

            try:
                self._logger.debug(
                    f"Processing text batch {batch_num}/{total_batches}",
                    extra={"batch_size": len(batch)},
                )
                embeddings = await self._text_embedder.embed_texts(texts)

                for chunk, embedding in zip(batch, embeddings, strict=True):
                    point = VectorPoint(
                        id=chunk.id,
                        vector=embedding.vector,
                        payload={
                            "video_id": video_id,
                            "chunk_id": chunk.id,
                            "modality": Modality.FRAME.value,
                            "start_time": chunk.start_time,
                            "end_time": chunk.end_time,
                            "frame_number": chunk.frame_number,
                            "description": chunk.description or "",
                        },
                    )
                    all_vectors.append(point)

            except Exception as e:
                failed += len(batch)
                self._logger.error(
                    f"Text batch {batch_num} embedding failed",
                    extra={
                        "batch_num": batch_num,
                        "batch_size": len(batch),
                        "error": str(e),
                    },
                )

        stored = 0
        if all_vectors:
            stored = await self._vector_db.upsert(self._text_collection, all_vectors)

        self._logger.info(
            "Frame text embedding completed",
            extra={
                "video_id": video_id,
                "total_frames": len(chunks),
                "frames_with_descriptions": len(chunks_with_desc),
                "embeddings_generated": len(all_vectors),
                "vectors_stored": stored,
                "failed": failed,
            },
        )

        return EmbeddingStats(
            total_items=len(chunks),
            text_embeddings=len(all_vectors),
            image_embeddings=0,
            vectors_stored=stored,
            failed_items=failed,
        )

    async def embed_chunks(
        self,
        chunks: list[AnyChunk],
        video_id: str,
    ) -> EmbeddingStats:
        """Embed a mixed list of chunks.

        Args:
            chunks: Mixed chunk types to embed.
            video_id: Parent video ID.

        Returns:
            Combined statistics.
        """
        transcript_chunks = [c for c in chunks if isinstance(c, TranscriptChunk)]
        frame_chunks = [c for c in chunks if isinstance(c, FrameChunk)]

        self._logger.info(
            "Starting mixed chunk embedding",
            extra={
                "video_id": video_id,
                "total_chunks": len(chunks),
                "transcript_chunks": len(transcript_chunks),
                "frame_chunks": len(frame_chunks),
            },
        )

        # Process different chunk types
        self._logger.debug("Embedding transcript chunks")
        transcript_stats = await self.embed_transcript_chunks(
            transcript_chunks, video_id
        )

        self._logger.debug("Embedding frame chunks")
        frame_stats = await self.embed_frame_chunks(frame_chunks, video_id)

        combined_stats = EmbeddingStats(
            total_items=transcript_stats.total_items + frame_stats.total_items,
            text_embeddings=transcript_stats.text_embeddings
            + frame_stats.text_embeddings,
            image_embeddings=frame_stats.image_embeddings,
            vectors_stored=transcript_stats.vectors_stored + frame_stats.vectors_stored,
            failed_items=transcript_stats.failed_items + frame_stats.failed_items,
        )

        self._logger.info(
            "Mixed chunk embedding completed",
            extra={
                "video_id": video_id,
                "total_items": combined_stats.total_items,
                "text_embeddings": combined_stats.text_embeddings,
                "image_embeddings": combined_stats.image_embeddings,
                "vectors_stored": combined_stats.vectors_stored,
                "failed_items": combined_stats.failed_items,
            },
        )

        return combined_stats

    async def delete_video_embeddings(self, video_id: str) -> int:
        """Delete all embeddings for a video.

        Args:
            video_id: Video ID to delete embeddings for.

        Returns:
            Number of vectors deleted.
        """
        self._logger.info(
            "Deleting video embeddings",
            extra={
                "video_id": video_id,
                "text_collection": self._text_collection,
                "image_collection": self._image_collection,
            },
        )

        deleted = 0

        # Delete from text collection
        self._logger.debug(
            "Deleting from text collection",
            extra={"collection": self._text_collection},
        )
        text_deleted = await self._vector_db.delete_by_filter(
            self._text_collection,
            {"video_id": video_id},
        )
        deleted += text_deleted

        # Delete from image collection if exists
        image_deleted = 0
        if self._image_collection:
            self._logger.debug(
                "Deleting from image collection",
                extra={"collection": self._image_collection},
            )
            image_deleted = await self._vector_db.delete_by_filter(
                self._image_collection,
                {"video_id": video_id},
            )
            deleted += image_deleted

        self._logger.info(
            "Video embeddings deleted",
            extra={
                "video_id": video_id,
                "text_deleted": text_deleted,
                "image_deleted": image_deleted,
                "total_deleted": deleted,
            },
        )

        return deleted

    async def _ensure_collection(self, name: str, dimensions: int) -> None:
        """Ensure a vector collection exists."""
        if not await self._vector_db.collection_exists(name):
            self._logger.debug(
                "Creating vector collection",
                extra={
                    "collection": name,
                    "dimensions": dimensions,
                    "distance_metric": "cosine",
                },
            )
            await self._vector_db.create_collection(
                name=name,
                vector_size=dimensions,
                distance_metric="cosine",
            )
