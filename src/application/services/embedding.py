"""Embedding orchestration service for batch embedding generation."""

from dataclasses import dataclass

from src.commons.infrastructure.vectordb.base import VectorDBBase, VectorPoint
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
        if not chunks:
            return EmbeddingStats(
                total_items=0,
                text_embeddings=0,
                image_embeddings=0,
                vectors_stored=0,
                failed_items=0,
            )

        # Ensure collection exists
        await self._ensure_collection(
            self._text_collection,
            self._text_embedder.text_dimensions,
        )

        # Process in batches
        batch_size = self._text_embedder.max_batch_size
        all_vectors: list[VectorPoint] = []
        failed = 0

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [chunk.text for chunk in batch]

            try:
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

            except Exception:
                failed += len(batch)

        # Store all vectors
        stored = 0
        if all_vectors:
            stored = await self._vector_db.upsert(self._text_collection, all_vectors)

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
        if not chunks:
            return EmbeddingStats(
                total_items=0,
                text_embeddings=0,
                image_embeddings=0,
                vectors_stored=0,
                failed_items=0,
            )

        # Use image embedder if available
        if self._image_embedder and self._image_collection:
            return await self._embed_frames_as_images(chunks, video_id)

        # Fall back to text embeddings of descriptions
        return await self._embed_frames_as_text(chunks, video_id)

    async def _embed_frames_as_images(
        self,
        chunks: list[FrameChunk],
        video_id: str,
    ) -> EmbeddingStats:
        """Embed frames using image embeddings."""
        if not self._image_embedder or not self._image_collection:
            return EmbeddingStats(
                total_items=len(chunks),
                text_embeddings=0,
                image_embeddings=0,
                vectors_stored=0,
                failed_items=len(chunks),
            )

        # Ensure collection exists
        if self._image_embedder.image_dimensions:
            await self._ensure_collection(
                self._image_collection,
                self._image_embedder.image_dimensions,
            )

        batch_size = self._image_embedder.max_batch_size
        all_vectors: list[VectorPoint] = []
        failed = 0

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            image_paths = [chunk.blob_path for chunk in batch]

            try:
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

            except Exception:
                failed += len(batch)

        stored = 0
        if all_vectors:
            stored = await self._vector_db.upsert(self._image_collection, all_vectors)

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

        if not chunks_with_desc:
            return EmbeddingStats(
                total_items=len(chunks),
                text_embeddings=0,
                image_embeddings=0,
                vectors_stored=0,
                failed_items=0,
            )

        batch_size = self._text_embedder.max_batch_size
        all_vectors: list[VectorPoint] = []
        failed = 0

        for i in range(0, len(chunks_with_desc), batch_size):
            batch = chunks_with_desc[i : i + batch_size]
            texts = [chunk.description for chunk in batch if chunk.description]

            try:
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

            except Exception:
                failed += len(batch)

        stored = 0
        if all_vectors:
            stored = await self._vector_db.upsert(self._text_collection, all_vectors)

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

        # Process different chunk types
        transcript_stats = await self.embed_transcript_chunks(
            transcript_chunks, video_id
        )
        frame_stats = await self.embed_frame_chunks(frame_chunks, video_id)

        return EmbeddingStats(
            total_items=transcript_stats.total_items + frame_stats.total_items,
            text_embeddings=transcript_stats.text_embeddings
            + frame_stats.text_embeddings,
            image_embeddings=frame_stats.image_embeddings,
            vectors_stored=transcript_stats.vectors_stored + frame_stats.vectors_stored,
            failed_items=transcript_stats.failed_items + frame_stats.failed_items,
        )

    async def delete_video_embeddings(self, video_id: str) -> int:
        """Delete all embeddings for a video.

        Args:
            video_id: Video ID to delete embeddings for.

        Returns:
            Number of vectors deleted.
        """
        deleted = 0

        # Delete from text collection
        deleted += await self._vector_db.delete_by_filter(
            self._text_collection,
            {"video_id": video_id},
        )

        # Delete from image collection if exists
        if self._image_collection:
            deleted += await self._vector_db.delete_by_filter(
                self._image_collection,
                {"video_id": video_id},
            )

        return deleted

    async def _ensure_collection(self, name: str, dimensions: int) -> None:
        """Ensure a vector collection exists."""
        if not await self._vector_db.collection_exists(name):
            await self._vector_db.create_collection(
                name=name,
                vector_size=dimensions,
                distance_metric="cosine",
            )
