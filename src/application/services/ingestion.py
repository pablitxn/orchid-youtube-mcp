"""Video ingestion orchestration service."""

import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.application.dtos.ingestion import (
    IngestionProgress,
    IngestionStatus,
    IngestVideoRequest,
    IngestVideoResponse,
    ProcessingStep,
)
from src.commons.infrastructure.blob.base import BlobStorageBase
from src.commons.infrastructure.documentdb.base import DocumentDBBase
from src.commons.infrastructure.vectordb.base import VectorDBBase, VectorPoint
from src.commons.settings.models import Settings
from src.domain.models.chunk import (
    FrameChunk,
    Modality,
    TranscriptChunk,
    WordTimestamp,
)
from src.domain.models.video import VideoMetadata, VideoStatus
from src.infrastructure.embeddings.base import EmbeddingServiceBase
from src.infrastructure.transcription.base import (
    TranscriptionResult,
    TranscriptionServiceBase,
)
from src.infrastructure.video.base import FrameExtractorBase
from src.infrastructure.youtube.base import YouTubeDownloaderBase
from src.infrastructure.youtube.downloader import DownloadError, VideoNotFoundError


class IngestionError(Exception):
    """Base exception for ingestion errors."""

    def __init__(self, message: str, step: ProcessingStep) -> None:
        self.step = step
        super().__init__(message)


class VideoIngestionService:
    """Orchestrates the complete video ingestion pipeline.

    Pipeline steps:
    1. Validate URL and check for duplicates
    2. Download video and audio from YouTube
    3. Transcribe audio with word-level timestamps
    4. Extract frames at configured intervals
    5. Create transcript chunks with overlap
    6. Generate embeddings for all chunks
    7. Store everything in appropriate databases
    """

    def __init__(
        self,
        youtube_downloader: YouTubeDownloaderBase,
        transcription_service: TranscriptionServiceBase,
        text_embedding_service: EmbeddingServiceBase,
        frame_extractor: FrameExtractorBase,
        blob_storage: BlobStorageBase,
        vector_db: VectorDBBase,
        document_db: DocumentDBBase,
        settings: Settings,
    ) -> None:
        """Initialize ingestion service with dependencies.

        Args:
            youtube_downloader: YouTube video downloader.
            transcription_service: Audio transcription service.
            text_embedding_service: Text embedding generator.
            frame_extractor: Video frame extractor.
            blob_storage: Blob storage for media files.
            vector_db: Vector database for embeddings.
            document_db: Document database for metadata.
            settings: Application settings.
        """
        self._downloader = youtube_downloader
        self._transcriber = transcription_service
        self._text_embedder = text_embedding_service
        self._frame_extractor = frame_extractor
        self._blob = blob_storage
        self._vector_db = vector_db
        self._document_db = document_db
        self._settings = settings

        # Collection/bucket names from settings
        self._videos_collection = settings.document_db.collections.videos
        self._chunks_collection = settings.document_db.collections.transcript_chunks
        self._frames_collection = settings.document_db.collections.frame_chunks
        self._vectors_collection = settings.vector_db.collections.transcripts
        self._videos_bucket = settings.blob_storage.buckets.videos
        self._frames_bucket = settings.blob_storage.buckets.frames

    async def ingest(  # noqa: PLR0912, PLR0915
        self,
        request: IngestVideoRequest,
        progress_callback: Callable[[IngestionProgress], None] | None = None,
    ) -> IngestVideoResponse:
        """Ingest a YouTube video through the complete pipeline.

        Uses blob-first architecture: raw files are uploaded to blob storage
        immediately after download, making the pipeline resilient to failures.
        If a failure occurs after upload, the pipeline can resume without
        re-downloading from YouTube.

        Args:
            request: Ingestion request with URL and options.
            progress_callback: Optional callback for progress updates.

        Returns:
            Response with video ID and ingestion results.

        Raises:
            IngestionError: If any pipeline step fails.
        """
        started_at = datetime.now(UTC)
        video_metadata: VideoMetadata | None = None

        def report_progress(
            step: ProcessingStep,
            step_progress: float,
            overall: float,
            message: str,
        ) -> None:
            if progress_callback:
                progress_callback(
                    IngestionProgress(
                        current_step=step,
                        step_progress=step_progress,
                        overall_progress=overall,
                        message=message,
                        started_at=started_at,
                    )
                )

        try:
            # Step 1: Validate URL
            report_progress(ProcessingStep.VALIDATING, 0.0, 0.0, "Validating URL...")
            if not self._downloader.validate_url(request.url):
                raise IngestionError(
                    f"Invalid YouTube URL: {request.url}",
                    ProcessingStep.VALIDATING,
                )

            video_id = self._downloader.extract_video_id(request.url)
            if not video_id:
                raise IngestionError(
                    "Could not extract video ID from URL",
                    ProcessingStep.VALIDATING,
                )

            # Check for existing video - with resume capability
            existing = await self._document_db.find_one(
                self._videos_collection,
                {"youtube_id": video_id},
            )

            if existing:
                existing_metadata = VideoMetadata(**existing)

                # If already completed, return existing response
                if existing_metadata.status == VideoStatus.READY:
                    return await self._build_response_from_existing(
                        existing, started_at
                    )

                # Check if we can resume from blob storage
                if await self._check_raw_blobs_exist(existing_metadata):
                    report_progress(
                        ProcessingStep.VALIDATING,
                        1.0,
                        0.1,
                        "Resuming from previous attempt...",
                    )
                    return await self._resume_from_status(
                        existing_metadata, request, report_progress
                    )

                # Raw blobs don't exist, need to re-download
                # Clean up any orphaned blobs and delete the incomplete record
                await self._cleanup_video_data(existing_metadata)
                await self._document_db.delete(
                    self._videos_collection, existing_metadata.id
                )

            report_progress(
                ProcessingStep.VALIDATING,
                1.0,
                0.05,
                "URL validated, starting download...",
            )

            # Phase 1: Download and upload to blob storage (blob-first)
            video_metadata = await self._download_and_store_raw(
                request, report_progress
            )

            # Phase 2: Transcribe from blob
            video_metadata, transcription = await self._transcribe_from_blob(
                video_metadata, request.language_hint, report_progress
            )

            # Phase 3: Extract frames from blob (if requested)
            frames: list[FrameChunk] = []
            if request.extract_frames:
                frames = await self._extract_frames_from_blob(
                    video_metadata, report_progress
                )

            # Phase 4: Create transcript chunks
            report_progress(
                ProcessingStep.CHUNKING, 0.0, 0.5, "Creating transcript chunks..."
            )

            transcript_chunks = self._create_transcript_chunks(
                transcription_segments=transcription.segments,
                video_id=video_metadata.id,
                language=transcription.language,
            )

            report_progress(
                ProcessingStep.CHUNKING,
                1.0,
                0.6,
                f"Created {len(transcript_chunks)} transcript chunks",
            )

            # Phase 5: Generate embeddings
            report_progress(
                ProcessingStep.EMBEDDING, 0.0, 0.6, "Generating embeddings..."
            )

            video_metadata = video_metadata.model_copy(
                update={"status": VideoStatus.EMBEDDING}
            )
            await self._update_video_status(video_metadata)

            await self._generate_and_store_embeddings(
                chunks=transcript_chunks,
                video_id=video_metadata.id,
            )

            report_progress(ProcessingStep.EMBEDDING, 1.0, 0.85, "Embeddings complete")

            # Phase 6: Store chunks in document DB
            report_progress(ProcessingStep.STORING, 0.0, 0.85, "Storing chunks...")

            if transcript_chunks:
                await self._document_db.insert_many(
                    self._chunks_collection,
                    [c.model_dump(mode="json") for c in transcript_chunks],
                )

            if frames:
                await self._document_db.insert_many(
                    self._frames_collection,
                    [f.model_dump(mode="json") for f in frames],
                )

            # Update final metadata
            video_metadata = video_metadata.model_copy(
                update={
                    "status": VideoStatus.READY,
                    "transcript_chunk_count": len(transcript_chunks),
                    "frame_chunk_count": len(frames),
                    "updated_at": datetime.now(UTC),
                }
            )
            await self._update_video_status(video_metadata)

            report_progress(ProcessingStep.COMPLETED, 1.0, 1.0, "Ingestion complete!")

            return IngestVideoResponse(
                video_id=video_metadata.id,
                youtube_id=video_metadata.youtube_id,
                title=video_metadata.title,
                duration_seconds=video_metadata.duration_seconds,
                status=IngestionStatus.COMPLETED,
                chunk_counts={
                    "transcript": len(transcript_chunks),
                    "frame": len(frames),
                },
                created_at=video_metadata.created_at,
            )

        except VideoNotFoundError as e:
            if video_metadata:
                await self._mark_failed(video_metadata, str(e))
            raise IngestionError(str(e), ProcessingStep.DOWNLOADING) from e

        except DownloadError as e:
            if video_metadata:
                await self._mark_failed(video_metadata, str(e))
            raise IngestionError(str(e), ProcessingStep.DOWNLOADING) from e

        except Exception as e:
            if video_metadata:
                await self._mark_failed(video_metadata, str(e))
            raise IngestionError(
                f"Ingestion failed: {e}",
                ProcessingStep.FAILED,
            ) from e

    async def _ensure_bucket_exists(self, bucket: str) -> None:
        """Ensure a storage bucket exists."""
        if not await self._blob.bucket_exists(bucket):
            await self._blob.create_bucket(bucket)

    async def _update_video_status(self, video: VideoMetadata) -> None:
        """Update video metadata in document DB."""
        await self._document_db.update(
            self._videos_collection,
            video.id,
            video.model_dump(mode="json"),
        )

    async def _mark_failed(self, video: VideoMetadata, error: str) -> None:
        """Mark video as failed."""
        failed_video = video.mark_failed(error)
        await self._update_video_status(failed_video)

    async def _cleanup_video_data(self, video: VideoMetadata) -> None:
        """Clean up all data associated with a video.

        Removes blobs, chunks, and embeddings but NOT the video document itself.
        Used when restarting a failed ingestion from scratch.

        Args:
            video: Video metadata to clean up.
        """
        try:
            # Delete blobs in videos bucket
            video_blobs = await self._blob.list_blobs(
                self._videos_bucket,
                prefix=f"{video.id}/",
            )
            for blob in video_blobs:
                await self._blob.delete(self._videos_bucket, blob.path)

            # Delete blobs in frames bucket
            frame_blobs = await self._blob.list_blobs(
                self._frames_bucket,
                prefix=f"{video.id}/",
            )
            for blob in frame_blobs:
                await self._blob.delete(self._frames_bucket, blob.path)

            # Delete chunks from document DB
            await self._document_db.delete_many(
                self._chunks_collection,
                {"video_id": video.id},
            )
            await self._document_db.delete_many(
                self._frames_collection,
                {"video_id": video.id},
            )

            # Delete embeddings from vector DB
            await self._vector_db.delete_by_filter(
                self._vectors_collection,
                {"video_id": video.id},
            )
        except Exception:
            # Ignore cleanup errors - best effort
            pass

    async def _check_raw_blobs_exist(self, video_metadata: VideoMetadata) -> bool:
        """Check if raw video and audio blobs exist in storage.

        Used to determine if we can resume a failed ingestion without
        re-downloading from YouTube.

        Args:
            video_metadata: Video metadata with blob paths.

        Returns:
            True if both video and audio blobs exist.
        """
        if not video_metadata.blob_path_video or not video_metadata.blob_path_audio:
            return False

        video_exists = await self._blob.exists(
            self._videos_bucket, video_metadata.blob_path_video
        )
        audio_exists = await self._blob.exists(
            self._videos_bucket, video_metadata.blob_path_audio
        )

        return video_exists and audio_exists

    async def _download_and_store_raw(
        self,
        request: IngestVideoRequest,
        report_progress: Callable[[ProcessingStep, float, float, str], None],
    ) -> VideoMetadata:
        """Download from YouTube and immediately upload to blob storage.

        This is Phase 1 of blob-first architecture: download raw files and
        upload them to blob storage before any processing. Once uploaded,
        the pipeline can resume from blob storage if it fails later.

        Args:
            request: Ingestion request with URL and options.
            report_progress: Progress callback function.

        Returns:
            VideoMetadata with blob paths populated.
        """
        report_progress(ProcessingStep.DOWNLOADING, 0.0, 0.1, "Downloading video...")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Download from YouTube
            download_result = await self._downloader.download(
                url=request.url,
                output_dir=temp_path,
                max_resolution=request.max_resolution,
            )

            # Create metadata from YouTube info
            yt_meta = download_result.metadata
            video_metadata = VideoMetadata(
                youtube_id=yt_meta.id,
                youtube_url=request.url,
                title=yt_meta.title,
                description=yt_meta.description,
                duration_seconds=yt_meta.duration_seconds,
                channel_name=yt_meta.channel_name,
                channel_id=yt_meta.channel_id,
                upload_date=yt_meta.upload_date,
                thumbnail_url=yt_meta.thumbnail_url,
                status=VideoStatus.DOWNLOADING,
            )

            # Save initial metadata to document DB
            await self._document_db.insert(
                self._videos_collection,
                video_metadata.model_dump(mode="json"),
            )

            report_progress(
                ProcessingStep.DOWNLOADING, 0.5, 0.15, "Uploading to storage..."
            )

            # Define blob paths
            video_blob_path = f"{video_metadata.id}/video.mp4"
            audio_blob_path = f"{video_metadata.id}/audio.mp3"

            await self._ensure_bucket_exists(self._videos_bucket)

            # Upload video file (pass file handle, not bytes, for large files)
            with download_result.video_path.open("rb") as vf:
                await self._blob.upload(
                    self._videos_bucket,
                    video_blob_path,
                    vf,
                    content_type="video/mp4",
                )

            # Upload audio file
            with download_result.audio_path.open("rb") as af:
                await self._blob.upload(
                    self._videos_bucket,
                    audio_blob_path,
                    af,
                    content_type="audio/mpeg",
                )

            # Update metadata with blob paths
            video_metadata = video_metadata.model_copy(
                update={
                    "blob_path_video": video_blob_path,
                    "blob_path_audio": audio_blob_path,
                    "status": VideoStatus.TRANSCRIBING,
                }
            )
            await self._update_video_status(video_metadata)

            report_progress(ProcessingStep.DOWNLOADING, 1.0, 0.2, "Download complete")

        # Temp files deleted here, but raw files are safe in blob storage
        return video_metadata

    async def _transcribe_from_blob(
        self,
        video_metadata: VideoMetadata,
        language_hint: str | None,
        report_progress: Callable[[ProcessingStep, float, float, str], None],
    ) -> tuple[VideoMetadata, TranscriptionResult]:
        """Download audio from blob and transcribe.

        This is Phase 2 of blob-first architecture: download audio from
        blob storage to a temp file, transcribe, then clean up.

        Args:
            video_metadata: Video metadata with audio blob path.
            language_hint: Optional language hint for transcription.
            report_progress: Progress callback function.

        Returns:
            Tuple of updated VideoMetadata and TranscriptionResult.
        """
        report_progress(
            ProcessingStep.TRANSCRIBING,
            0.0,
            0.2,
            "Preparing audio for transcription...",
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_local_path = temp_path / "audio.mp3"

            # Download audio from blob to temp file
            await self._blob.download_to_file(
                self._videos_bucket,
                video_metadata.blob_path_audio,  # type: ignore[arg-type]
                audio_local_path,
            )

            report_progress(
                ProcessingStep.TRANSCRIBING, 0.2, 0.25, "Transcribing audio..."
            )

            # Transcribe
            transcription = await self._transcriber.transcribe(
                audio_path=str(audio_local_path),
                language_hint=language_hint,
                word_timestamps=True,
            )

        # Temp file deleted here

        video_metadata = video_metadata.model_copy(
            update={
                "language": transcription.language,
                "status": VideoStatus.EXTRACTING,
            }
        )
        await self._update_video_status(video_metadata)

        report_progress(ProcessingStep.TRANSCRIBING, 1.0, 0.4, "Transcription complete")

        return video_metadata, transcription

    async def _extract_frames_from_blob(
        self,
        video_metadata: VideoMetadata,
        report_progress: Callable[[ProcessingStep, float, float, str], None],
    ) -> list[FrameChunk]:
        """Download video from blob and extract frames.

        This is Phase 3 of blob-first architecture: download video from
        blob storage to a temp file, extract frames, upload them, then clean up.

        Args:
            video_metadata: Video metadata with video blob path.
            report_progress: Progress callback function.

        Returns:
            List of extracted FrameChunks.
        """
        report_progress(
            ProcessingStep.EXTRACTING_FRAMES,
            0.0,
            0.4,
            "Preparing video for frame extraction...",
        )

        interval = self._settings.chunking.frame.interval_seconds
        frames: list[FrameChunk] = []

        await self._ensure_bucket_exists(self._frames_bucket)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video_local_path = temp_path / "video.mp4"
            frames_output_dir = temp_path / "frames"
            frames_output_dir.mkdir()

            # Download video from blob to temp file
            await self._blob.download_to_file(
                self._videos_bucket,
                video_metadata.blob_path_video,  # type: ignore[arg-type]
                video_local_path,
            )

            report_progress(
                ProcessingStep.EXTRACTING_FRAMES, 0.2, 0.45, "Extracting frames..."
            )

            # Extract frames using ffmpeg
            extracted = await self._frame_extractor.extract_frames(
                video_path=video_local_path,
                output_dir=frames_output_dir,
                interval_seconds=interval,
            )

            report_progress(
                ProcessingStep.EXTRACTING_FRAMES, 0.7, 0.48, "Uploading frames..."
            )

            # Upload frames to blob storage
            for i, extracted_frame in enumerate(extracted):
                timestamp = extracted_frame.timestamp
                if timestamp >= video_metadata.duration_seconds:
                    break

                blob_path = f"{video_metadata.id}/frames/frame_{i:05d}.jpg"
                thumb_path = f"{video_metadata.id}/frames/thumb_{i:05d}.jpg"

                with extracted_frame.path.open("rb") as f:
                    frame_bytes = f.read()
                    await self._blob.upload(
                        self._frames_bucket,
                        blob_path,
                        frame_bytes,
                        content_type="image/jpeg",
                    )
                    # Use same image as thumbnail for now
                    await self._blob.upload(
                        self._frames_bucket,
                        thumb_path,
                        frame_bytes,
                        content_type="image/jpeg",
                    )

                frame_chunk = FrameChunk(
                    video_id=video_metadata.id,
                    frame_number=extracted_frame.frame_number,
                    start_time=timestamp,
                    end_time=timestamp + interval,
                    blob_path=blob_path,
                    thumbnail_path=thumb_path,
                    width=extracted_frame.width,
                    height=extracted_frame.height,
                )
                frames.append(frame_chunk)

        # Temp files deleted here

        report_progress(
            ProcessingStep.EXTRACTING_FRAMES,
            1.0,
            0.5,
            f"Extracted {len(frames)} frames",
        )

        return frames

    async def _extract_frames(
        self,
        video_path: Path,
        video_id: str,
        duration_seconds: int,
    ) -> list[FrameChunk]:
        """Extract frames from video at configured intervals."""
        interval = self._settings.chunking.frame.interval_seconds
        frames: list[FrameChunk] = []

        await self._ensure_bucket_exists(self._frames_bucket)

        with tempfile.TemporaryDirectory() as frames_dir:
            frames_path = Path(frames_dir)

            # Extract frames using ffmpeg
            extracted = await self._frame_extractor.extract_frames(
                video_path=video_path,
                output_dir=frames_path,
                interval_seconds=interval,
            )

            for i, extracted_frame in enumerate(extracted):
                timestamp = extracted_frame.timestamp
                if timestamp >= duration_seconds:
                    break

                # Upload frame to blob storage
                blob_path = f"{video_id}/frames/frame_{i:05d}.jpg"
                thumb_path = f"{video_id}/frames/thumb_{i:05d}.jpg"

                with extracted_frame.path.open("rb") as f:
                    frame_bytes = f.read()
                    await self._blob.upload(
                        self._frames_bucket,
                        blob_path,
                        frame_bytes,
                        content_type="image/jpeg",
                    )
                    # Use same image as thumbnail for now
                    await self._blob.upload(
                        self._frames_bucket,
                        thumb_path,
                        frame_bytes,
                        content_type="image/jpeg",
                    )

                frame_chunk = FrameChunk(
                    video_id=video_id,
                    frame_number=extracted_frame.frame_number,
                    start_time=timestamp,
                    end_time=timestamp + interval,
                    blob_path=blob_path,
                    thumbnail_path=thumb_path,
                    width=extracted_frame.width,
                    height=extracted_frame.height,
                )
                frames.append(frame_chunk)

        return frames

    def _create_transcript_chunks(
        self,
        transcription_segments: list[Any],
        video_id: str,
        language: str,
    ) -> list[TranscriptChunk]:
        """Create transcript chunks from transcription segments.

        Uses settings for chunk duration and overlap.
        """
        chunk_seconds = self._settings.chunking.transcript.chunk_seconds
        overlap_seconds = self._settings.chunking.transcript.overlap_seconds

        if not transcription_segments:
            return []

        chunks: list[TranscriptChunk] = []
        current_start = 0.0
        segment_idx = 0

        while segment_idx < len(transcription_segments):
            chunk_end = current_start + chunk_seconds
            chunk_text_parts: list[str] = []
            chunk_words: list[WordTimestamp] = []
            chunk_confidences: list[float] = []
            actual_end = current_start

            # Collect segments that fall within this chunk
            while segment_idx < len(transcription_segments):
                seg = transcription_segments[segment_idx]
                seg_start = seg.start_time
                seg_end = seg.end_time

                # If segment starts after chunk end, stop
                if seg_start >= chunk_end:
                    break

                chunk_text_parts.append(seg.text)
                chunk_confidences.append(seg.confidence)
                actual_end = max(actual_end, seg_end)

                # Add word timestamps
                for word in seg.words:
                    chunk_words.append(
                        WordTimestamp(
                            word=word.word,
                            start_time=word.start_time,
                            end_time=word.end_time,
                            confidence=word.confidence,
                        )
                    )

                segment_idx += 1

            if chunk_text_parts:
                avg_confidence = sum(chunk_confidences) / len(chunk_confidences)
                chunk = TranscriptChunk(
                    video_id=video_id,
                    text=" ".join(chunk_text_parts),
                    language=language,
                    confidence=avg_confidence,
                    start_time=current_start,
                    end_time=actual_end,
                    word_timestamps=chunk_words,
                )
                chunks.append(chunk)

            # Move to next chunk with overlap
            current_start = chunk_end - overlap_seconds
            current_start = max(current_start, 0)

            # Rewind segment index for overlap
            while (
                segment_idx > 0
                and transcription_segments[segment_idx - 1].start_time >= current_start
            ):
                segment_idx -= 1

        return chunks

    async def _generate_and_store_embeddings(
        self,
        chunks: list[TranscriptChunk],
        video_id: str,
    ) -> None:
        """Generate embeddings for chunks and store in vector DB."""
        if not chunks:
            return

        # Ensure collection exists
        if not await self._vector_db.collection_exists(self._vectors_collection):
            await self._vector_db.create_collection(
                name=self._vectors_collection,
                vector_size=self._text_embedder.text_dimensions,
                distance_metric="cosine",
            )

        # Batch embed texts
        texts = [chunk.text for chunk in chunks]
        batch_size = self._text_embedder.max_batch_size

        all_vectors: list[VectorPoint] = []

        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i : i + batch_size]
            batch_chunks = chunks[i : i + batch_size]

            embeddings = await self._text_embedder.embed_texts(batch_texts)

            for chunk, embedding in zip(batch_chunks, embeddings, strict=True):
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
                    },
                )
                all_vectors.append(point)

        # Upsert all vectors
        await self._vector_db.upsert(self._vectors_collection, all_vectors)

    async def _build_response_from_existing(
        self,
        existing: dict[str, Any],
        started_at: datetime,
    ) -> IngestVideoResponse:
        """Build response from existing video document."""
        status = IngestionStatus.COMPLETED
        if existing.get("status") == VideoStatus.FAILED.value:
            status = IngestionStatus.FAILED
        elif existing.get("status") != VideoStatus.READY.value:
            status = IngestionStatus.IN_PROGRESS

        return IngestVideoResponse(
            video_id=existing["id"],
            youtube_id=existing["youtube_id"],
            title=existing["title"],
            duration_seconds=existing["duration_seconds"],
            status=status,
            error_message=existing.get("error_message"),
            chunk_counts={
                "transcript": existing.get("transcript_chunk_count", 0),
                "frame": existing.get("frame_chunk_count", 0),
                "audio": existing.get("audio_chunk_count", 0),
                "video": existing.get("video_chunk_count", 0),
            },
            created_at=existing.get("created_at", started_at),
        )

    async def _resume_from_status(
        self,
        video_metadata: VideoMetadata,
        request: IngestVideoRequest,
        report_progress: Callable[[ProcessingStep, float, float, str], None],
    ) -> IngestVideoResponse:
        """Resume ingestion from the last successful step.

        Determines which step to resume from based on VideoStatus and
        continues the pipeline from there.

        Args:
            video_metadata: Video metadata with current status.
            request: Original ingestion request.
            report_progress: Progress callback function.

        Returns:
            IngestVideoResponse after completing remaining steps.
        """
        transcription: TranscriptionResult | None = None
        frames: list[FrameChunk] = []

        # Determine starting point based on status
        if video_metadata.status in (
            VideoStatus.DOWNLOADING,
            VideoStatus.TRANSCRIBING,
            VideoStatus.FAILED,
        ):
            # Need to transcribe (or re-transcribe if failed during transcription)
            video_metadata, transcription = await self._transcribe_from_blob(
                video_metadata, request.language_hint, report_progress
            )

        if video_metadata.status == VideoStatus.EXTRACTING and request.extract_frames:
            # Extract frames if requested
            frames = await self._extract_frames_from_blob(
                video_metadata, report_progress
            )

        # Continue with chunking, embedding, storing
        # Note: If we resumed, we may not have transcription data
        # In that case, we need to re-transcribe to get the segments
        if transcription is None:
            # Re-transcribe to get segments for chunking
            video_metadata, transcription = await self._transcribe_from_blob(
                video_metadata, request.language_hint, report_progress
            )

        # Create transcript chunks
        report_progress(
            ProcessingStep.CHUNKING, 0.0, 0.5, "Creating transcript chunks..."
        )

        transcript_chunks = self._create_transcript_chunks(
            transcription_segments=transcription.segments,
            video_id=video_metadata.id,
            language=transcription.language,
        )

        report_progress(
            ProcessingStep.CHUNKING,
            1.0,
            0.6,
            f"Created {len(transcript_chunks)} transcript chunks",
        )

        # Generate embeddings
        report_progress(ProcessingStep.EMBEDDING, 0.0, 0.6, "Generating embeddings...")

        video_metadata = video_metadata.model_copy(
            update={"status": VideoStatus.EMBEDDING}
        )
        await self._update_video_status(video_metadata)

        await self._generate_and_store_embeddings(
            chunks=transcript_chunks,
            video_id=video_metadata.id,
        )

        report_progress(ProcessingStep.EMBEDDING, 1.0, 0.85, "Embeddings complete")

        # Store chunks in document DB
        report_progress(ProcessingStep.STORING, 0.0, 0.85, "Storing chunks...")

        if transcript_chunks:
            await self._document_db.insert_many(
                self._chunks_collection,
                [c.model_dump(mode="json") for c in transcript_chunks],
            )

        if frames:
            await self._document_db.insert_many(
                self._frames_collection,
                [f.model_dump(mode="json") for f in frames],
            )

        # Update final metadata
        video_metadata = video_metadata.model_copy(
            update={
                "status": VideoStatus.READY,
                "transcript_chunk_count": len(transcript_chunks),
                "frame_chunk_count": len(frames),
                "updated_at": datetime.now(UTC),
            }
        )
        await self._update_video_status(video_metadata)

        report_progress(ProcessingStep.COMPLETED, 1.0, 1.0, "Ingestion complete!")

        return IngestVideoResponse(
            video_id=video_metadata.id,
            youtube_id=video_metadata.youtube_id,
            title=video_metadata.title,
            duration_seconds=video_metadata.duration_seconds,
            status=IngestionStatus.COMPLETED,
            chunk_counts={
                "transcript": len(transcript_chunks),
                "frame": len(frames),
            },
            created_at=video_metadata.created_at,
        )

    async def get_ingestion_status(self, video_id: str) -> IngestVideoResponse | None:
        """Get current ingestion status for a video.

        Args:
            video_id: Internal video UUID.

        Returns:
            Current status or None if not found.
        """
        doc = await self._document_db.find_by_id(self._videos_collection, video_id)
        if not doc:
            return None

        return await self._build_response_from_existing(doc, datetime.now(UTC))

    async def list_videos(
        self,
        status: VideoStatus | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> list[IngestVideoResponse]:
        """List ingested videos with optional filtering.

        Args:
            status: Optional status filter.
            skip: Number of videos to skip.
            limit: Maximum videos to return.

        Returns:
            List of video responses.
        """
        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status.value

        docs = await self._document_db.find(
            self._videos_collection,
            filters,
            skip=skip,
            limit=limit,
            sort=[("created_at", -1)],
        )

        responses = []
        for doc in docs:
            resp = await self._build_response_from_existing(doc, datetime.now(UTC))
            responses.append(resp)

        return responses

    async def delete_video(self, video_id: str) -> bool:
        """Delete a video and all associated data.

        Args:
            video_id: Internal video UUID.

        Returns:
            True if deleted, False if not found.
        """
        # Check if video exists
        doc = await self._document_db.find_by_id(self._videos_collection, video_id)
        if not doc:
            return False

        # Delete from vector DB
        await self._vector_db.delete_by_filter(
            self._vectors_collection,
            {"video_id": video_id},
        )

        # Delete chunks from document DB
        await self._document_db.delete_many(
            self._chunks_collection,
            {"video_id": video_id},
        )
        await self._document_db.delete_many(
            self._frames_collection,
            {"video_id": video_id},
        )

        # Delete blobs
        try:
            blobs = await self._blob.list_blobs(
                self._videos_bucket,
                prefix=f"{video_id}/",
            )
            for blob in blobs:
                await self._blob.delete(self._videos_bucket, blob.path)

            frames = await self._blob.list_blobs(
                self._frames_bucket,
                prefix=f"{video_id}/",
            )
            for frame in frames:
                await self._blob.delete(self._frames_bucket, frame.path)
        except Exception:
            pass  # Ignore blob deletion errors

        # Delete video document
        return await self._document_db.delete(self._videos_collection, video_id)
