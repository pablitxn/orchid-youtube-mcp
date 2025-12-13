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
from src.commons.telemetry import LogContext, get_logger
from src.domain.models.chunk import (
    AudioChunk,
    FrameChunk,
    Modality,
    TranscriptChunk,
    VideoChunk,
    WordTimestamp,
)
from src.domain.models.video import VideoMetadata, VideoStatus
from src.infrastructure.embeddings.base import EmbeddingServiceBase
from src.infrastructure.transcription.base import (
    TranscriptionResult,
    TranscriptionServiceBase,
)
from src.infrastructure.video.base import FrameExtractorBase, VideoChunkerBase
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
        video_chunker: VideoChunkerBase | None = None,
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
            video_chunker: Optional video/audio chunker for segment extraction.
        """
        self._downloader = youtube_downloader
        self._transcriber = transcription_service
        self._text_embedder = text_embedding_service
        self._frame_extractor = frame_extractor
        self._video_chunker = video_chunker
        self._blob = blob_storage
        self._vector_db = vector_db
        self._document_db = document_db
        self._settings = settings
        self._logger = get_logger(__name__)

        # Collection/bucket names from settings
        self._videos_collection = settings.document_db.collections.videos
        self._chunks_collection = settings.document_db.collections.transcript_chunks
        self._frames_collection = settings.document_db.collections.frame_chunks
        self._audio_chunks_collection = settings.document_db.collections.audio_chunks
        self._video_chunks_collection = settings.document_db.collections.video_chunks
        self._vectors_collection = settings.vector_db.collections.transcripts
        self._videos_bucket = settings.blob_storage.buckets.videos
        self._frames_bucket = settings.blob_storage.buckets.frames
        self._chunks_bucket = settings.blob_storage.buckets.chunks

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

        self._logger.info(
            "Starting video ingestion",
            extra={
                "url": request.url,
                "extract_frames": request.extract_frames,
                "extract_audio_chunks": request.extract_audio_chunks,
                "max_resolution": request.max_resolution,
                "language_hint": request.language_hint,
            },
        )

        def report_progress(
            step: ProcessingStep,
            step_progress: float,
            overall: float,
            message: str,
        ) -> None:
            self._logger.debug(
                "Progress update",
                extra={
                    "step": step.value,
                    "step_progress": step_progress,
                    "overall_progress": overall,
                    "progress_message": message,
                },
            )
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
            self._logger.debug("Validating YouTube URL", extra={"url": request.url})
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

            self._logger.debug(
                "YouTube video ID extracted",
                extra={"youtube_id": video_id},
            )

            # Check for existing video - with resume capability
            self._logger.debug(
                "Checking for existing video in database",
                extra={"youtube_id": video_id},
            )
            existing = await self._document_db.find_one(
                self._videos_collection,
                {"youtube_id": video_id},
            )

            if existing:
                existing_metadata = VideoMetadata(**existing)
                self._logger.info(
                    "Found existing video record",
                    extra={
                        "video_id": existing_metadata.id,
                        "youtube_id": existing_metadata.youtube_id,
                        "status": existing_metadata.status.value,
                    },
                )

                # If already completed, return existing response
                if existing_metadata.status == VideoStatus.READY:
                    self._logger.info(
                        "Video already ingested, returning existing record",
                        extra={"video_id": existing_metadata.id},
                    )
                    return await self._build_response_from_existing(
                        existing, started_at
                    )

                # Check if we can resume from blob storage
                blobs_exist = await self._check_raw_blobs_exist(existing_metadata)
                self._logger.debug(
                    "Checked raw blobs existence for resume",
                    extra={
                        "video_id": existing_metadata.id,
                        "blobs_exist": blobs_exist,
                        "blob_path_video": existing_metadata.blob_path_video,
                        "blob_path_audio": existing_metadata.blob_path_audio,
                    },
                )

                if blobs_exist:
                    self._logger.info(
                        "Resuming ingestion from blob storage",
                        extra={
                            "video_id": existing_metadata.id,
                            "resume_from_status": existing_metadata.status.value,
                        },
                    )
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
                self._logger.warning(
                    "Raw blobs not found, cleaning up and re-downloading",
                    extra={
                        "video_id": existing_metadata.id,
                        "status": existing_metadata.status.value,
                    },
                )
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
            self._logger.debug("Starting Phase 1: Download and upload to blob storage")
            video_metadata = await self._download_and_store_raw(
                request, report_progress
            )

            # Use LogContext to add video_id to all subsequent logs
            with LogContext(
                video_id=video_metadata.id, youtube_id=video_metadata.youtube_id
            ):
                self._logger.info(
                    "Phase 1 complete: Video downloaded and stored in blob",
                    extra={
                        "title": video_metadata.title,
                        "duration_seconds": video_metadata.duration_seconds,
                        "blob_path_video": video_metadata.blob_path_video,
                        "blob_path_audio": video_metadata.blob_path_audio,
                    },
                )

                # Phase 2: Transcribe from blob
                self._logger.debug("Starting Phase 2: Transcription")
                video_metadata, transcription = await self._transcribe_from_blob(
                    video_metadata, request.language_hint, report_progress
                )
                self._logger.info(
                    "Phase 2 complete: Audio transcribed",
                    extra={
                        "language": transcription.language,
                        "segment_count": len(transcription.segments),
                        "duration_seconds": transcription.duration_seconds,
                    },
                )

                # Phase 3: Extract frames from blob (if requested)
                frames: list[FrameChunk] = []
                if request.extract_frames:
                    self._logger.debug("Starting Phase 3: Frame extraction")
                    frames = await self._extract_frames_from_blob(
                        video_metadata, report_progress
                    )
                    self._logger.info(
                        "Phase 3 complete: Frames extracted",
                        extra={"frame_count": len(frames)},
                    )
                else:
                    self._logger.debug(
                        "Skipping Phase 3: Frame extraction not requested"
                    )

                # Phase 3b: Extract audio chunks from blob (if requested)
                audio_chunks: list[AudioChunk] = []
                if request.extract_audio_chunks and self._video_chunker:
                    self._logger.debug("Starting Phase 3b: Audio chunk extraction")
                    audio_chunks = await self._extract_audio_chunks_from_blob(
                        video_metadata, report_progress
                    )
                    self._logger.info(
                        "Phase 3b complete: Audio chunks extracted",
                        extra={"audio_chunk_count": len(audio_chunks)},
                    )
                elif request.extract_audio_chunks and not self._video_chunker:
                    self._logger.warning(
                        "Audio chunk extraction requested but video_chunker "
                        "not available"
                    )

                # Phase 3c: Extract video chunks from blob (if requested)
                video_chunks: list[VideoChunk] = []
                if request.extract_video_chunks and self._video_chunker:
                    self._logger.debug("Starting Phase 3c: Video chunk extraction")
                    video_chunks = await self._extract_video_chunks_from_blob(
                        video_metadata, report_progress
                    )
                    self._logger.info(
                        "Phase 3c complete: Video chunks extracted",
                        extra={"video_chunk_count": len(video_chunks)},
                    )
                elif request.extract_video_chunks and not self._video_chunker:
                    self._logger.warning(
                        "Video chunk extraction requested but video_chunker "
                        "not available"
                    )

                # Phase 4: Create transcript chunks
                chunk_settings = self._settings.chunking.transcript
                self._logger.debug(
                    "Starting Phase 4: Creating transcript chunks",
                    extra={
                        "chunk_seconds": chunk_settings.chunk_seconds,
                        "overlap_seconds": chunk_settings.overlap_seconds,
                    },
                )
                report_progress(
                    ProcessingStep.CHUNKING, 0.0, 0.5, "Creating transcript chunks..."
                )

                transcript_chunks = self._create_transcript_chunks(
                    transcription_segments=transcription.segments,
                    video_id=video_metadata.id,
                    language=transcription.language,
                )

                self._logger.info(
                    "Phase 4 complete: Transcript chunks created",
                    extra={"chunk_count": len(transcript_chunks)},
                )
                report_progress(
                    ProcessingStep.CHUNKING,
                    1.0,
                    0.6,
                    f"Created {len(transcript_chunks)} transcript chunks",
                )

                # Phase 5: Generate embeddings
                self._logger.debug(
                    "Starting Phase 5: Generating embeddings",
                    extra={
                        "chunk_count": len(transcript_chunks),
                        "embedding_dimensions": self._text_embedder.text_dimensions,
                    },
                )
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

                self._logger.info("Phase 5 complete: Embeddings generated and stored")
                report_progress(
                    ProcessingStep.EMBEDDING, 1.0, 0.85, "Embeddings complete"
                )

                # Phase 6: Store chunks in document DB
                self._logger.debug("Starting Phase 6: Storing chunks in document DB")
                report_progress(ProcessingStep.STORING, 0.0, 0.85, "Storing chunks...")

                if transcript_chunks:
                    self._logger.debug(
                        "Inserting transcript chunks",
                        extra={"count": len(transcript_chunks)},
                    )
                    await self._document_db.insert_many(
                        self._chunks_collection,
                        [c.model_dump(mode="json") for c in transcript_chunks],
                    )

                if frames:
                    self._logger.debug(
                        "Inserting frame chunks",
                        extra={"count": len(frames)},
                    )
                    await self._document_db.insert_many(
                        self._frames_collection,
                        [f.model_dump(mode="json") for f in frames],
                    )

                if audio_chunks:
                    self._logger.debug(
                        "Inserting audio chunks",
                        extra={"count": len(audio_chunks)},
                    )
                    await self._document_db.insert_many(
                        self._audio_chunks_collection,
                        [a.model_dump(mode="json") for a in audio_chunks],
                    )

                if video_chunks:
                    self._logger.debug(
                        "Inserting video chunks",
                        extra={"count": len(video_chunks)},
                    )
                    await self._document_db.insert_many(
                        self._video_chunks_collection,
                        [v.model_dump(mode="json") for v in video_chunks],
                    )

                self._logger.info("Phase 6 complete: Chunks stored in document DB")

                # Update final metadata
                video_metadata = video_metadata.model_copy(
                    update={
                        "status": VideoStatus.READY,
                        "transcript_chunk_count": len(transcript_chunks),
                        "frame_chunk_count": len(frames),
                        "audio_chunk_count": len(audio_chunks),
                        "video_chunk_count": len(video_chunks),
                        "updated_at": datetime.now(UTC),
                    }
                )
                await self._update_video_status(video_metadata)

                elapsed_seconds = (datetime.now(UTC) - started_at).total_seconds()
                self._logger.info(
                    "Ingestion completed successfully",
                    extra={
                        "elapsed_seconds": round(elapsed_seconds, 2),
                        "transcript_chunks": len(transcript_chunks),
                        "frame_chunks": len(frames),
                        "audio_chunks": len(audio_chunks),
                        "video_chunks": len(video_chunks),
                    },
                )
                report_progress(
                    ProcessingStep.COMPLETED, 1.0, 1.0, "Ingestion complete!"
                )

                return IngestVideoResponse(
                    video_id=video_metadata.id,
                    youtube_id=video_metadata.youtube_id,
                    title=video_metadata.title,
                    duration_seconds=video_metadata.duration_seconds,
                    status=IngestionStatus.COMPLETED,
                    chunk_counts={
                        "transcript": len(transcript_chunks),
                        "frame": len(frames),
                        "audio": len(audio_chunks),
                        "video": len(video_chunks),
                    },
                    created_at=video_metadata.created_at,
                )

        except VideoNotFoundError as e:
            self._logger.error(
                "Video not found on YouTube",
                extra={"url": request.url, "error": str(e)},
            )
            if video_metadata:
                await self._mark_failed(video_metadata, str(e))
            raise IngestionError(str(e), ProcessingStep.DOWNLOADING) from e

        except DownloadError as e:
            self._logger.error(
                "Download failed",
                extra={"url": request.url, "error": str(e)},
            )
            if video_metadata:
                await self._mark_failed(video_metadata, str(e))
            raise IngestionError(str(e), ProcessingStep.DOWNLOADING) from e

        except Exception as e:
            self._logger.exception(
                "Ingestion failed with unexpected error",
                extra={
                    "url": request.url,
                    "video_id": video_metadata.id if video_metadata else None,
                    "error": str(e),
                },
            )
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

            # Delete blobs in chunks bucket (audio/video chunks)
            if await self._blob.bucket_exists(self._chunks_bucket):
                chunk_blobs = await self._blob.list_blobs(
                    self._chunks_bucket,
                    prefix=f"{video.id}/",
                )
                for blob in chunk_blobs:
                    await self._blob.delete(self._chunks_bucket, blob.path)

            # Delete chunks from document DB
            await self._document_db.delete_many(
                self._chunks_collection,
                {"video_id": video.id},
            )
            await self._document_db.delete_many(
                self._frames_collection,
                {"video_id": video.id},
            )
            await self._document_db.delete_many(
                self._audio_chunks_collection,
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
            self._logger.debug(
                "Created temporary directory for download",
                extra={"temp_dir": temp_dir},
            )

            # Download from YouTube
            self._logger.debug(
                "Starting YouTube download",
                extra={"url": request.url, "max_resolution": request.max_resolution},
            )
            download_result = await self._downloader.download(
                url=request.url,
                output_dir=temp_path,
                max_resolution=request.max_resolution,
            )

            # Log downloaded file sizes
            video_size_mb = download_result.video_path.stat().st_size / (1024 * 1024)
            audio_size_mb = download_result.audio_path.stat().st_size / (1024 * 1024)
            self._logger.debug(
                "YouTube download complete",
                extra={
                    "video_path": str(download_result.video_path),
                    "audio_path": str(download_result.audio_path),
                    "video_size_mb": round(video_size_mb, 2),
                    "audio_size_mb": round(audio_size_mb, 2),
                },
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

            self._logger.debug(
                "Video metadata created",
                extra={
                    "video_id": video_metadata.id,
                    "youtube_id": video_metadata.youtube_id,
                    "title": video_metadata.title,
                    "duration_seconds": video_metadata.duration_seconds,
                    "channel_name": video_metadata.channel_name,
                },
            )

            # Save initial metadata to document DB
            self._logger.debug("Inserting initial metadata to document DB")
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
            self._logger.debug(
                "Uploading video to blob storage",
                extra={
                    "bucket": self._videos_bucket,
                    "blob_path": video_blob_path,
                    "size_mb": round(video_size_mb, 2),
                },
            )
            with download_result.video_path.open("rb") as vf:
                await self._blob.upload(
                    self._videos_bucket,
                    video_blob_path,
                    vf,
                    content_type="video/mp4",
                )
            self._logger.debug("Video upload complete")

            # Upload audio file
            self._logger.debug(
                "Uploading audio to blob storage",
                extra={
                    "bucket": self._videos_bucket,
                    "blob_path": audio_blob_path,
                    "size_mb": round(audio_size_mb, 2),
                },
            )
            with download_result.audio_path.open("rb") as af:
                await self._blob.upload(
                    self._videos_bucket,
                    audio_blob_path,
                    af,
                    content_type="audio/mpeg",
                )
            self._logger.debug("Audio upload complete")

            # Update metadata with blob paths
            video_metadata = video_metadata.model_copy(
                update={
                    "blob_path_video": video_blob_path,
                    "blob_path_audio": audio_blob_path,
                    "status": VideoStatus.TRANSCRIBING,
                }
            )
            await self._update_video_status(video_metadata)
            self._logger.debug(
                "Metadata updated with blob paths",
                extra={
                    "blob_path_video": video_blob_path,
                    "blob_path_audio": audio_blob_path,
                    "new_status": VideoStatus.TRANSCRIBING.value,
                },
            )

            report_progress(ProcessingStep.DOWNLOADING, 1.0, 0.2, "Download complete")

        # Temp files deleted here, but raw files are safe in blob storage
        self._logger.debug("Temporary directory cleaned up, raw files safe in blob")
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

        self._logger.debug(
            "Starting transcription phase",
            extra={
                "video_id": video_metadata.id,
                "blob_path_audio": video_metadata.blob_path_audio,
                "language_hint": language_hint,
            },
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_local_path = temp_path / "audio.mp3"

            self._logger.debug(
                "Downloading audio from blob to temp file",
                extra={
                    "temp_dir": temp_dir,
                    "target_path": str(audio_local_path),
                },
            )

            # Download audio from blob to temp file
            await self._blob.download_to_file(
                self._videos_bucket,
                video_metadata.blob_path_audio,  # type: ignore[arg-type]
                audio_local_path,
            )

            audio_size_mb = audio_local_path.stat().st_size / (1024 * 1024)
            self._logger.debug(
                "Audio downloaded to temp file",
                extra={"size_mb": round(audio_size_mb, 2)},
            )

            report_progress(
                ProcessingStep.TRANSCRIBING, 0.2, 0.25, "Transcribing audio..."
            )

            # Transcribe
            self._logger.debug("Calling transcription service")
            transcription = await self._transcriber.transcribe(
                audio_path=str(audio_local_path),
                language_hint=language_hint,
                word_timestamps=True,
            )

            self._logger.debug(
                "Transcription service returned",
                extra={
                    "language": transcription.language,
                    "duration_seconds": transcription.duration_seconds,
                    "segment_count": len(transcription.segments),
                    "word_count": sum(len(seg.words) for seg in transcription.segments),
                },
            )

        # Temp file deleted here
        self._logger.debug("Transcription temp directory cleaned up")

        video_metadata = video_metadata.model_copy(
            update={
                "language": transcription.language,
                "status": VideoStatus.EXTRACTING,
            }
        )
        await self._update_video_status(video_metadata)

        self._logger.debug(
            "Video metadata updated after transcription",
            extra={
                "language": transcription.language,
                "new_status": VideoStatus.EXTRACTING.value,
            },
        )

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

        self._logger.debug(
            "Starting frame extraction phase",
            extra={
                "video_id": video_metadata.id,
                "blob_path_video": video_metadata.blob_path_video,
                "interval_seconds": interval,
                "duration_seconds": video_metadata.duration_seconds,
                "expected_frames": int(video_metadata.duration_seconds / interval),
            },
        )

        await self._ensure_bucket_exists(self._frames_bucket)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video_local_path = temp_path / "video.mp4"
            frames_output_dir = temp_path / "frames"
            frames_output_dir.mkdir()

            self._logger.debug(
                "Downloading video from blob to temp file",
                extra={"temp_dir": temp_dir, "target_path": str(video_local_path)},
            )

            # Download video from blob to temp file
            await self._blob.download_to_file(
                self._videos_bucket,
                video_metadata.blob_path_video,  # type: ignore[arg-type]
                video_local_path,
            )

            video_size_mb = video_local_path.stat().st_size / (1024 * 1024)
            self._logger.debug(
                "Video downloaded to temp file",
                extra={"size_mb": round(video_size_mb, 2)},
            )

            report_progress(
                ProcessingStep.EXTRACTING_FRAMES, 0.2, 0.45, "Extracting frames..."
            )

            # Extract frames using ffmpeg
            self._logger.debug("Calling frame extractor (ffmpeg)")
            extracted = await self._frame_extractor.extract_frames(
                video_path=video_local_path,
                output_dir=frames_output_dir,
                interval_seconds=interval,
            )

            self._logger.debug(
                "Frame extraction complete",
                extra={"extracted_count": len(extracted)},
            )

            report_progress(
                ProcessingStep.EXTRACTING_FRAMES, 0.7, 0.48, "Uploading frames..."
            )

            self._logger.debug(
                "Starting frame upload to blob storage",
                extra={"bucket": self._frames_bucket, "frame_count": len(extracted)},
            )

            # Upload frames to blob storage
            for i, extracted_frame in enumerate(extracted):
                timestamp = extracted_frame.timestamp
                if timestamp >= video_metadata.duration_seconds:
                    self._logger.debug(
                        "Stopping frame upload - timestamp exceeds duration",
                        extra={
                            "frame_index": i,
                            "timestamp": timestamp,
                            "duration": video_metadata.duration_seconds,
                        },
                    )
                    break

                blob_path = f"{video_metadata.id}/frames/frame_{i:05d}.jpg"
                thumb_path = f"{video_metadata.id}/frames/thumb_{i:05d}.jpg"

                # Upload full-resolution frame
                with extracted_frame.path.open("rb") as f:
                    await self._blob.upload(
                        self._frames_bucket,
                        blob_path,
                        f,
                        content_type="image/jpeg",
                    )

                # Upload thumbnail (generated by frame extractor)
                if (
                    extracted_frame.thumbnail_path
                    and extracted_frame.thumbnail_path.exists()
                ):
                    with extracted_frame.thumbnail_path.open("rb") as f:
                        await self._blob.upload(
                            self._frames_bucket,
                            thumb_path,
                            f,
                            content_type="image/jpeg",
                        )
                else:
                    # Fallback: use same image as thumbnail if not generated
                    with extracted_frame.path.open("rb") as f:
                        await self._blob.upload(
                            self._frames_bucket,
                            thumb_path,
                            f,
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

            self._logger.debug(
                "Frame upload complete",
                extra={"uploaded_count": len(frames)},
            )

        # Temp files deleted here
        self._logger.debug("Frame extraction temp directory cleaned up")

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

                # Upload full-resolution frame
                with extracted_frame.path.open("rb") as f:
                    await self._blob.upload(
                        self._frames_bucket,
                        blob_path,
                        f,
                        content_type="image/jpeg",
                    )

                # Upload thumbnail (generated by frame extractor)
                if (
                    extracted_frame.thumbnail_path
                    and extracted_frame.thumbnail_path.exists()
                ):
                    with extracted_frame.thumbnail_path.open("rb") as f:
                        await self._blob.upload(
                            self._frames_bucket,
                            thumb_path,
                            f,
                            content_type="image/jpeg",
                        )
                else:
                    # Fallback: use same image as thumbnail if not generated
                    with extracted_frame.path.open("rb") as f:
                        await self._blob.upload(
                            self._frames_bucket,
                            thumb_path,
                            f,
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

    async def _extract_audio_chunks_from_blob(
        self,
        video_metadata: VideoMetadata,
        report_progress: Callable[[ProcessingStep, float, float, str], None],
    ) -> list[AudioChunk]:
        """Download audio from blob and extract audio chunks.

        This is Phase 3b of blob-first architecture: download audio from
        blob storage to a temp file, extract audio segments, upload them,
        then clean up.

        Args:
            video_metadata: Video metadata with audio blob path.
            report_progress: Progress callback function.

        Returns:
            List of extracted AudioChunks.
        """
        report_progress(
            ProcessingStep.EXTRACTING_AUDIO,
            0.0,
            0.42,
            "Preparing audio for chunking...",
        )

        chunk_seconds = self._settings.chunking.audio.chunk_seconds
        audio_chunks: list[AudioChunk] = []

        self._logger.debug(
            "Starting audio chunk extraction phase",
            extra={
                "video_id": video_metadata.id,
                "blob_path_audio": video_metadata.blob_path_audio,
                "chunk_seconds": chunk_seconds,
                "duration_seconds": video_metadata.duration_seconds,
                "expected_chunks": (video_metadata.duration_seconds // chunk_seconds)
                + 1,
            },
        )

        await self._ensure_bucket_exists(self._chunks_bucket)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            audio_local_path = temp_path / "audio.mp3"
            audio_output_dir = temp_path / "audio_chunks"
            audio_output_dir.mkdir()

            self._logger.debug(
                "Downloading audio from blob to temp file",
                extra={"temp_dir": temp_dir, "target_path": str(audio_local_path)},
            )

            # Download audio from blob to temp file
            await self._blob.download_to_file(
                self._videos_bucket,
                video_metadata.blob_path_audio,  # type: ignore[arg-type]
                audio_local_path,
            )

            audio_size_mb = audio_local_path.stat().st_size / (1024 * 1024)
            self._logger.debug(
                "Audio downloaded to temp file",
                extra={"size_mb": round(audio_size_mb, 2)},
            )

            report_progress(
                ProcessingStep.EXTRACTING_AUDIO,
                0.2,
                0.44,
                "Extracting audio segments...",
            )

            # Extract audio chunks using ffmpeg
            assert self._video_chunker is not None
            self._logger.debug("Calling video chunker for audio segmentation")
            extracted_segments = await self._video_chunker.chunk_audio(
                audio_path=audio_local_path,
                output_dir=audio_output_dir,
                chunk_seconds=chunk_seconds,
                format="mp3",
                bitrate="192k",
            )

            self._logger.debug(
                "Audio chunk extraction complete",
                extra={"extracted_count": len(extracted_segments)},
            )

            if not extracted_segments:
                self._logger.warning(
                    "No audio chunks were extracted from the audio file. "
                    "This could indicate ffprobe failed to get duration or "
                    "the audio file is corrupted/empty.",
                    extra={
                        "video_id": video_metadata.id,
                        "audio_local_path": str(audio_local_path),
                        "chunk_seconds": chunk_seconds,
                    },
                )
                return []

            report_progress(
                ProcessingStep.EXTRACTING_AUDIO,
                0.6,
                0.46,
                "Uploading audio chunks...",
            )

            self._logger.debug(
                "Starting audio chunk upload to blob storage",
                extra={
                    "bucket": self._chunks_bucket,
                    "chunk_count": len(extracted_segments),
                },
            )

            # Upload audio chunks to blob storage
            for i, segment in enumerate(extracted_segments):
                blob_path = f"{video_metadata.id}/audio/audio_{i:05d}.mp3"

                with segment.path.open("rb") as f:
                    await self._blob.upload(
                        self._chunks_bucket,
                        blob_path,
                        f,
                        content_type="audio/mpeg",
                    )

                audio_chunk = AudioChunk(
                    video_id=video_metadata.id,
                    start_time=segment.start_time,
                    end_time=segment.end_time,
                    blob_path=blob_path,
                    format="mp3",
                )
                audio_chunks.append(audio_chunk)

            self._logger.debug(
                "Audio chunk upload complete",
                extra={"uploaded_count": len(audio_chunks)},
            )

        # Temp files deleted here
        self._logger.debug("Audio chunk extraction temp directory cleaned up")

        report_progress(
            ProcessingStep.EXTRACTING_AUDIO,
            1.0,
            0.48,
            f"Extracted {len(audio_chunks)} audio chunks",
        )

        return audio_chunks

    async def _extract_video_chunks_from_blob(
        self,
        video_metadata: VideoMetadata,
        report_progress: Callable[[ProcessingStep, float, float, str], None],
    ) -> list[VideoChunk]:
        """Download video from blob and extract video chunks.

        This is Phase 3c of blob-first architecture: download video from
        blob storage to a temp file, extract video segments, upload them,
        then clean up.

        Args:
            video_metadata: Video metadata with video blob path.
            report_progress: Progress callback function.

        Returns:
            List of extracted VideoChunks.
        """
        report_progress(
            ProcessingStep.EXTRACTING_VIDEO,
            0.0,
            0.48,
            "Preparing video for chunking...",
        )

        chunk_settings = self._settings.chunking.video
        video_chunks: list[VideoChunk] = []

        self._logger.debug(
            "Starting video chunk extraction phase",
            extra={
                "video_id": video_metadata.id,
                "blob_path_video": video_metadata.blob_path_video,
                "chunk_seconds": chunk_settings.chunk_seconds,
                "overlap_seconds": chunk_settings.overlap_seconds,
                "max_size_mb": chunk_settings.max_size_mb,
                "duration_seconds": video_metadata.duration_seconds,
            },
        )

        await self._ensure_bucket_exists(self._chunks_bucket)

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            video_local_path = temp_path / "video.mp4"
            video_output_dir = temp_path / "video_chunks"
            video_output_dir.mkdir()

            self._logger.debug(
                "Downloading video from blob to temp file",
                extra={"temp_dir": temp_dir, "target_path": str(video_local_path)},
            )

            # Download video from blob to temp file
            await self._blob.download_to_file(
                self._videos_bucket,
                video_metadata.blob_path_video,  # type: ignore[arg-type]
                video_local_path,
            )

            video_size_mb = video_local_path.stat().st_size / (1024 * 1024)
            self._logger.debug(
                "Video downloaded to temp file",
                extra={"size_mb": round(video_size_mb, 2)},
            )

            report_progress(
                ProcessingStep.EXTRACTING_VIDEO,
                0.2,
                0.49,
                "Extracting video segments...",
            )

            # Extract video chunks using ffmpeg
            assert self._video_chunker is not None
            self._logger.debug("Calling video chunker for video segmentation")

            # Get video info for metadata
            video_info = await self._video_chunker.get_video_info(video_local_path)

            extracted_segments = await self._video_chunker.chunk_video(
                video_path=video_local_path,
                output_dir=video_output_dir,
                chunk_seconds=chunk_settings.chunk_seconds,
                overlap_seconds=chunk_settings.overlap_seconds,
                max_size_mb=chunk_settings.max_size_mb,
                format="mp4",
                include_audio=True,
            )

            self._logger.debug(
                "Video chunk extraction complete",
                extra={"extracted_count": len(extracted_segments)},
            )

            if not extracted_segments:
                self._logger.warning(
                    "No video chunks were extracted from the video file. "
                    "This could indicate ffprobe failed to get duration or "
                    "the video file is corrupted/empty.",
                    extra={
                        "video_id": video_metadata.id,
                        "video_local_path": str(video_local_path),
                        "chunk_seconds": chunk_settings.chunk_seconds,
                    },
                )
                return []

            report_progress(
                ProcessingStep.EXTRACTING_VIDEO,
                0.6,
                0.49,
                "Uploading video chunks...",
            )

            self._logger.debug(
                "Starting video chunk upload to blob storage",
                extra={
                    "bucket": self._chunks_bucket,
                    "chunk_count": len(extracted_segments),
                },
            )

            # Upload video chunks to blob storage
            for i, segment in enumerate(extracted_segments):
                blob_path = f"{video_metadata.id}/video/chunk_{i:05d}.mp4"

                with segment.path.open("rb") as f:
                    await self._blob.upload(
                        self._chunks_bucket,
                        blob_path,
                        f,
                        content_type="video/mp4",
                    )

                video_chunk = VideoChunk(
                    video_id=video_metadata.id,
                    start_time=segment.start_time,
                    end_time=segment.end_time,
                    blob_path=blob_path,
                    thumbnail_path="",  # No thumbnail for now
                    format="mp4",
                    width=video_info.width,
                    height=video_info.height,
                    fps=video_info.fps,
                    has_audio=segment.has_audio,
                    codec=video_info.codec,
                    size_bytes=segment.size_bytes,
                )
                video_chunks.append(video_chunk)

            self._logger.debug(
                "Video chunk upload complete",
                extra={"uploaded_count": len(video_chunks)},
            )

        # Temp files deleted here
        self._logger.debug("Video chunk extraction temp directory cleaned up")

        report_progress(
            ProcessingStep.EXTRACTING_VIDEO,
            1.0,
            0.50,
            f"Extracted {len(video_chunks)} video chunks",
        )

        return video_chunks

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
            # Use end_time > current_start to include segments that overlap
            # with the new chunk window, even if they started before current_start
            while (
                segment_idx > 0
                and transcription_segments[segment_idx - 1].end_time > current_start
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
            self._logger.debug("No chunks to embed, skipping embedding phase")
            return

        self._logger.debug(
            "Starting embedding generation",
            extra={
                "video_id": video_id,
                "chunk_count": len(chunks),
                "collection": self._vectors_collection,
            },
        )

        # Ensure collection exists
        collection_exists = await self._vector_db.collection_exists(
            self._vectors_collection
        )
        if not collection_exists:
            self._logger.debug(
                "Creating vector collection",
                extra={
                    "collection": self._vectors_collection,
                    "vector_size": self._text_embedder.text_dimensions,
                },
            )
            await self._vector_db.create_collection(
                name=self._vectors_collection,
                vector_size=self._text_embedder.text_dimensions,
                distance_metric="cosine",
            )

        # Batch embed texts
        texts = [chunk.text for chunk in chunks]
        batch_size = self._text_embedder.max_batch_size
        total_batches = (len(texts) + batch_size - 1) // batch_size

        self._logger.debug(
            "Embedding texts in batches",
            extra={
                "total_texts": len(texts),
                "batch_size": batch_size,
                "total_batches": total_batches,
            },
        )

        all_vectors: list[VectorPoint] = []

        for i in range(0, len(texts), batch_size):
            batch_num = i // batch_size + 1
            batch_texts = texts[i : i + batch_size]
            batch_chunks = chunks[i : i + batch_size]

            self._logger.debug(
                f"Processing embedding batch {batch_num}/{total_batches}",
                extra={"batch_size": len(batch_texts)},
            )

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

        # Log all chunks being embedded - FULL TEXT
        self._logger.warning(f"=== EMBEDDING {len(chunks)} CHUNKS ===")
        for i, chunk in enumerate(chunks):
            self._logger.warning(
                f"CHUNK {i} [{chunk.start_time:.1f}-{chunk.end_time:.1f}] "
                f"len={len(chunk.text)}: {chunk.text}"
            )

        # Ensure indexes exist for filtering
        await self._vector_db.ensure_payload_indexes(self._vectors_collection)

        # Upsert all vectors
        self._logger.warning(
            f"UPSERTING {len(all_vectors)} vectors to {self._vectors_collection}"
        )
        await self._vector_db.upsert(self._vectors_collection, all_vectors)
        self._logger.warning("UPSERT COMPLETE")

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

    async def _cleanup_existing_chunks(self, video_id: str) -> None:
        """Clean up existing chunks for a video before re-inserting.

        This ensures idempotency when resuming - we don't create duplicates.

        Args:
            video_id: The video ID to clean up chunks for.
        """
        self._logger.debug(
            "Cleaning up existing chunks before resume",
            extra={"video_id": video_id},
        )

        # Delete existing chunks from document DB
        await self._document_db.delete_many(
            self._chunks_collection,
            {"video_id": video_id},
        )
        await self._document_db.delete_many(
            self._frames_collection,
            {"video_id": video_id},
        )
        await self._document_db.delete_many(
            self._audio_chunks_collection,
            {"video_id": video_id},
        )

        # Delete existing embeddings from vector DB
        await self._vector_db.delete_by_filter(
            self._vectors_collection,
            {"video_id": video_id},
        )

        self._logger.debug("Existing chunks cleaned up")

    async def _resume_from_status(
        self,
        video_metadata: VideoMetadata,
        request: IngestVideoRequest,
        report_progress: Callable[[ProcessingStep, float, float, str], None],
    ) -> IngestVideoResponse:
        """Resume ingestion from the last successful step.

        Determines which step to resume from based on VideoStatus and
        continues the pipeline from there. Cleans up existing chunks
        to ensure idempotency.

        Args:
            video_metadata: Video metadata with current status.
            request: Original ingestion request.
            report_progress: Progress callback function.

        Returns:
            IngestVideoResponse after completing remaining steps.
        """
        transcription: TranscriptionResult | None = None
        frames: list[FrameChunk] = []
        audio_chunks: list[AudioChunk] = []
        video_chunks: list[VideoChunk] = []

        self._logger.info(
            "Resuming ingestion from previous state",
            extra={
                "video_id": video_metadata.id,
                "youtube_id": video_metadata.youtube_id,
                "current_status": video_metadata.status.value,
            },
        )

        # Clean up existing chunks to ensure idempotency
        await self._cleanup_existing_chunks(video_metadata.id)

        # Determine starting point based on status
        if video_metadata.status in (
            VideoStatus.DOWNLOADING,
            VideoStatus.TRANSCRIBING,
            VideoStatus.FAILED,
        ):
            self._logger.debug(
                "Resume: Starting from transcription phase",
                extra={"status": video_metadata.status.value},
            )
            # Need to transcribe (or re-transcribe if failed during transcription)
            video_metadata, transcription = await self._transcribe_from_blob(
                video_metadata, request.language_hint, report_progress
            )

        if video_metadata.status == VideoStatus.EXTRACTING and request.extract_frames:
            self._logger.debug("Resume: Extracting frames")
            # Extract frames if requested
            frames = await self._extract_frames_from_blob(
                video_metadata, report_progress
            )

        # Extract audio chunks if requested and chunker available
        if request.extract_audio_chunks and self._video_chunker:
            self._logger.debug("Resume: Extracting audio chunks")
            audio_chunks = await self._extract_audio_chunks_from_blob(
                video_metadata, report_progress
            )

        # Extract video chunks if requested and chunker available
        if request.extract_video_chunks and self._video_chunker:
            self._logger.debug("Resume: Extracting video chunks")
            video_chunks = await self._extract_video_chunks_from_blob(
                video_metadata, report_progress
            )

        # Continue with chunking, embedding, storing
        # Note: If we resumed, we may not have transcription data
        # In that case, we need to re-transcribe to get the segments
        if transcription is None:
            self._logger.debug(
                "Resume: No transcription data available, re-transcribing"
            )
            # Re-transcribe to get segments for chunking
            video_metadata, transcription = await self._transcribe_from_blob(
                video_metadata, request.language_hint, report_progress
            )

        # Create transcript chunks
        self._logger.debug("Resume: Creating transcript chunks")
        report_progress(
            ProcessingStep.CHUNKING, 0.0, 0.5, "Creating transcript chunks..."
        )

        transcript_chunks = self._create_transcript_chunks(
            transcription_segments=transcription.segments,
            video_id=video_metadata.id,
            language=transcription.language,
        )

        self._logger.debug(
            "Resume: Transcript chunks created",
            extra={"chunk_count": len(transcript_chunks)},
        )
        report_progress(
            ProcessingStep.CHUNKING,
            1.0,
            0.6,
            f"Created {len(transcript_chunks)} transcript chunks",
        )

        # Generate embeddings
        self._logger.debug("Resume: Generating embeddings")
        report_progress(ProcessingStep.EMBEDDING, 0.0, 0.6, "Generating embeddings...")

        video_metadata = video_metadata.model_copy(
            update={"status": VideoStatus.EMBEDDING}
        )
        await self._update_video_status(video_metadata)

        await self._generate_and_store_embeddings(
            chunks=transcript_chunks,
            video_id=video_metadata.id,
        )

        self._logger.debug("Resume: Embeddings complete")
        report_progress(ProcessingStep.EMBEDDING, 1.0, 0.85, "Embeddings complete")

        # Store chunks in document DB
        self._logger.debug("Resume: Storing chunks in document DB")
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

        if audio_chunks:
            await self._document_db.insert_many(
                self._audio_chunks_collection,
                [a.model_dump(mode="json") for a in audio_chunks],
            )

        if video_chunks:
            await self._document_db.insert_many(
                self._video_chunks_collection,
                [v.model_dump(mode="json") for v in video_chunks],
            )

        # Update final metadata
        video_metadata = video_metadata.model_copy(
            update={
                "status": VideoStatus.READY,
                "transcript_chunk_count": len(transcript_chunks),
                "frame_chunk_count": len(frames),
                "audio_chunk_count": len(audio_chunks),
                "video_chunk_count": len(video_chunks),
                "updated_at": datetime.now(UTC),
            }
        )
        await self._update_video_status(video_metadata)

        self._logger.info(
            "Resume: Ingestion completed successfully",
            extra={
                "video_id": video_metadata.id,
                "transcript_chunks": len(transcript_chunks),
                "frame_chunks": len(frames),
                "audio_chunks": len(audio_chunks),
                "video_chunks": len(video_chunks),
            },
        )
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
                "audio": len(audio_chunks),
                "video": len(video_chunks),
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

        Removes all related data including:
        - Vector embeddings (transcripts, frames, videos)
        - Document chunks (transcript, frame, audio, video)
        - Blob storage (videos, frames, chunks)
        - Video metadata

        Args:
            video_id: Internal video UUID.

        Returns:
            True if deleted, False if not found.
        """
        # Check if video exists
        doc = await self._document_db.find_by_id(self._videos_collection, video_id)
        if not doc:
            self._logger.info(
                "Video not found for deletion",
                extra={"video_id": video_id},
            )
            return False

        self._logger.info(
            "Starting video deletion",
            extra={"video_id": video_id},
        )

        # Delete from vector DB - all embedding collections
        vector_collections = [
            self._settings.vector_db.collections.transcripts,
            self._settings.vector_db.collections.frames,
            self._settings.vector_db.collections.videos,
        ]
        for collection in vector_collections:
            try:
                await self._vector_db.delete_by_filter(
                    collection,
                    {"video_id": video_id},
                )
                self._logger.debug(
                    "Deleted embeddings from collection",
                    extra={"video_id": video_id, "collection": collection},
                )
            except Exception as e:
                self._logger.warning(
                    "Failed to delete from vector collection",
                    extra={
                        "video_id": video_id,
                        "collection": collection,
                        "error": str(e),
                    },
                )

        # Delete all chunk types from document DB
        chunk_collections = [
            self._chunks_collection,
            self._frames_collection,
            self._audio_chunks_collection,
            self._video_chunks_collection,
        ]
        for collection in chunk_collections:
            try:
                await self._document_db.delete_many(
                    collection,
                    {"video_id": video_id},
                )
                self._logger.debug(
                    "Deleted chunks from collection",
                    extra={"video_id": video_id, "collection": collection},
                )
            except Exception as e:
                self._logger.warning(
                    "Failed to delete from chunk collection",
                    extra={
                        "video_id": video_id,
                        "collection": collection,
                        "error": str(e),
                    },
                )

        # Delete blobs from all buckets
        blob_buckets = [
            self._videos_bucket,
            self._frames_bucket,
            self._chunks_bucket,
        ]
        for bucket in blob_buckets:
            try:
                blobs = await self._blob.list_blobs(
                    bucket,
                    prefix=f"{video_id}/",
                )
                for blob in blobs:
                    await self._blob.delete(bucket, blob.path)
                self._logger.debug(
                    "Deleted blobs from bucket",
                    extra={
                        "video_id": video_id,
                        "bucket": bucket,
                        "blob_count": len(blobs),
                    },
                )
            except Exception as e:
                self._logger.warning(
                    "Failed to delete blobs from bucket",
                    extra={
                        "video_id": video_id,
                        "bucket": bucket,
                        "error": str(e),
                    },
                )

        # Delete video metadata document
        deleted = await self._document_db.delete(self._videos_collection, video_id)

        self._logger.info(
            "Video deletion completed",
            extra={"video_id": video_id, "success": deleted},
        )

        return deleted
