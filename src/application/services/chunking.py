"""Chunking service for creating content chunks from raw media."""

from dataclasses import dataclass
from pathlib import Path

from src.commons.settings.models import ChunkingSettings
from src.commons.telemetry import get_logger
from src.domain.models.chunk import (
    AudioChunk,
    FrameChunk,
    TranscriptChunk,
    VideoChunk,
    WordTimestamp,
)
from src.infrastructure.transcription.base import TranscriptionSegment
from src.infrastructure.video.base import FrameExtractorBase, VideoChunkerBase


@dataclass
class ChunkingResult:
    """Result from chunking operations."""

    transcript_chunks: list[TranscriptChunk]
    frame_chunks: list[FrameChunk]
    audio_chunks: list[AudioChunk]
    video_chunks: list[VideoChunk]


class ChunkingService:
    """Service for creating chunks from different media types.

    Handles:
    - Transcript chunking with overlap
    - Frame extraction at intervals
    - Audio segmentation
    - Video segment creation
    """

    def __init__(
        self,
        frame_extractor: FrameExtractorBase,
        video_chunker: VideoChunkerBase | None = None,
        settings: ChunkingSettings | None = None,
    ) -> None:
        """Initialize chunking service.

        Args:
            frame_extractor: Frame extraction utility.
            video_chunker: Video segmentation utility.
            settings: Chunking configuration.
        """
        self._frame_extractor = frame_extractor
        self._video_chunker = video_chunker
        self._settings = settings or ChunkingSettings()
        self._logger = get_logger(__name__)

    def create_transcript_chunks(
        self,
        segments: list[TranscriptionSegment],
        video_id: str,
        language: str,
    ) -> list[TranscriptChunk]:
        """Create transcript chunks from transcription segments.

        Chunks are created with configurable duration and overlap to ensure
        context is preserved across chunk boundaries.

        Args:
            segments: Transcription segments with word timestamps.
            video_id: Parent video ID.
            language: Detected language code.

        Returns:
            List of transcript chunks.
        """
        self._logger.debug(
            "Starting transcript chunking",
            extra={
                "video_id": video_id,
                "language": language,
                "segment_count": len(segments),
                "chunk_seconds": self._settings.transcript.chunk_seconds,
                "overlap_seconds": self._settings.transcript.overlap_seconds,
            },
        )

        if not segments:
            self._logger.debug("No segments provided, returning empty list")
            return []

        chunk_seconds = self._settings.transcript.chunk_seconds
        overlap_seconds = self._settings.transcript.overlap_seconds

        chunks: list[TranscriptChunk] = []
        current_start = 0.0
        segment_idx = 0

        while segment_idx < len(segments):
            chunk_end = current_start + chunk_seconds
            chunk_text_parts: list[str] = []
            chunk_words: list[WordTimestamp] = []
            chunk_confidences: list[float] = []
            actual_end = current_start

            # Collect segments that fall within this chunk window
            temp_idx = segment_idx
            while temp_idx < len(segments):
                seg = segments[temp_idx]

                # If segment starts after chunk end, stop collecting
                if seg.start_time >= chunk_end:
                    break

                chunk_text_parts.append(seg.text)
                chunk_confidences.append(seg.confidence)
                actual_end = max(actual_end, seg.end_time)

                # Add word-level timestamps
                for word in seg.words:
                    chunk_words.append(
                        WordTimestamp(
                            word=word.word,
                            start_time=word.start_time,
                            end_time=word.end_time,
                            confidence=word.confidence,
                        )
                    )

                temp_idx += 1

            # Create chunk if we have content
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

            # Advance to next chunk window with overlap
            current_start = chunk_end - overlap_seconds

            # Rewind segment index for overlap
            # Use end_time > current_start to include segments that overlap
            # with the new chunk window, even if they started before current_start
            while temp_idx > 0 and segments[temp_idx - 1].end_time > current_start:
                temp_idx -= 1
            segment_idx = temp_idx

        total_words = sum(len(c.word_timestamps) for c in chunks)
        avg_confidence = (
            sum(c.confidence for c in chunks) / len(chunks) if chunks else 0.0
        )
        self._logger.info(
            "Transcript chunking completed",
            extra={
                "video_id": video_id,
                "chunks_created": len(chunks),
                "total_words": total_words,
                "avg_confidence": round(avg_confidence, 3),
                "time_span_seconds": chunks[-1].end_time if chunks else 0,
            },
        )

        return chunks

    async def extract_frame_chunks(
        self,
        video_path: Path,
        video_id: str,
        duration_seconds: float,
        output_dir: Path,
    ) -> list[FrameChunk]:
        """Extract frames from video at configured intervals.

        Args:
            video_path: Path to video file.
            video_id: Parent video ID.
            duration_seconds: Total video duration.
            output_dir: Directory to save extracted frames.

        Returns:
            List of frame chunks with paths to extracted images.
        """
        interval = self._settings.frame.interval_seconds
        expected_frames = int(duration_seconds / interval) + 1

        self._logger.debug(
            "Starting frame extraction",
            extra={
                "video_id": video_id,
                "video_path": str(video_path),
                "duration_seconds": duration_seconds,
                "interval_seconds": interval,
                "expected_frames": expected_frames,
                "output_dir": str(output_dir),
            },
        )

        frames: list[FrameChunk] = []

        # Extract frames using ffmpeg
        self._logger.debug("Calling frame extractor (ffmpeg)")
        extracted = await self._frame_extractor.extract_frames(
            video_path=video_path,
            output_dir=output_dir,
            interval_seconds=interval,
        )

        self._logger.debug(
            "Frame extractor returned",
            extra={"extracted_count": len(extracted)},
        )

        for extracted_frame in extracted:
            timestamp = extracted_frame.timestamp
            if timestamp >= duration_seconds:
                break

            thumb = extracted_frame.thumbnail_path or extracted_frame.path
            frame_chunk = FrameChunk(
                video_id=video_id,
                frame_number=extracted_frame.frame_number,
                start_time=timestamp,
                end_time=min(timestamp + interval, duration_seconds),
                blob_path=str(extracted_frame.path),
                thumbnail_path=str(thumb),
                width=extracted_frame.width,
                height=extracted_frame.height,
            )
            frames.append(frame_chunk)

        self._logger.info(
            "Frame extraction completed",
            extra={
                "video_id": video_id,
                "frames_created": len(frames),
                "expected_frames": expected_frames,
                "first_frame_time": frames[0].start_time if frames else None,
                "last_frame_time": frames[-1].start_time if frames else None,
            },
        )

        return frames

    async def create_audio_chunks(
        self,
        audio_path: Path,
        video_id: str,
        duration_seconds: float,
        output_dir: Path,
    ) -> list[AudioChunk]:
        """Create audio chunks from audio file.

        Args:
            audio_path: Path to audio file (for future use with actual extraction).
            video_id: Parent video ID.
            duration_seconds: Total audio duration.
            output_dir: Directory to save audio chunks.

        Returns:
            List of audio chunks.
        """
        chunk_seconds = self._settings.audio.chunk_seconds
        num_chunks = int(duration_seconds / chunk_seconds) + 1

        self._logger.debug(
            "Starting audio chunking",
            extra={
                "video_id": video_id,
                "audio_path": str(audio_path),
                "duration_seconds": duration_seconds,
                "chunk_seconds": chunk_seconds,
                "expected_chunks": num_chunks,
                "output_dir": str(output_dir),
            },
        )

        chunks: list[AudioChunk] = []

        for i in range(num_chunks):
            start_time = i * chunk_seconds
            end_time = min((i + 1) * chunk_seconds, duration_seconds)

            if start_time >= duration_seconds:
                break

            # Path for this chunk (actual extraction would be done separately)
            chunk_path = output_dir / f"audio_{i:05d}.mp3"

            chunk = AudioChunk(
                video_id=video_id,
                start_time=start_time,
                end_time=end_time,
                blob_path=str(chunk_path),
                format="mp3",
            )
            chunks.append(chunk)

        self._logger.info(
            "Audio chunking completed",
            extra={
                "video_id": video_id,
                "chunks_created": len(chunks),
                "total_duration_seconds": chunks[-1].end_time if chunks else 0,
            },
        )

        return chunks

    async def create_video_chunks(
        self,
        video_path: Path,
        video_id: str,
        duration_seconds: float,
        output_dir: Path,
    ) -> list[VideoChunk]:
        """Create video segment chunks for multimodal LLM analysis.

        Args:
            video_path: Path to video file.
            video_id: Parent video ID.
            duration_seconds: Total video duration.
            output_dir: Directory to save video chunks.

        Returns:
            List of video chunks.
        """
        if not self._video_chunker:
            self._logger.warning(
                "Video chunker not available, skipping video chunk creation",
                extra={"video_id": video_id},
            )
            return []

        chunk_seconds = self._settings.video.chunk_seconds
        overlap_seconds = self._settings.video.overlap_seconds
        max_size_mb = self._settings.video.max_size_mb

        self._logger.debug(
            "Starting video chunking",
            extra={
                "video_id": video_id,
                "video_path": str(video_path),
                "duration_seconds": duration_seconds,
                "chunk_seconds": chunk_seconds,
                "overlap_seconds": overlap_seconds,
                "max_size_mb": max_size_mb,
                "output_dir": str(output_dir),
            },
        )

        chunks: list[VideoChunk] = []
        current_start = 0.0
        chunk_idx = 0
        skipped_for_size = 0

        while current_start < duration_seconds:
            end_time = min(current_start + chunk_seconds, duration_seconds)

            # Generate chunk path
            chunk_path = output_dir / f"video_{chunk_idx:05d}.mp4"
            thumb_path = output_dir / f"thumb_{chunk_idx:05d}.jpg"

            # Extract video segment
            await self._video_chunker.extract_segment(
                video_path=video_path,
                output_path=chunk_path,
                start_time=current_start,
                end_time=end_time,
            )

            # Get chunk file size
            size_bytes = chunk_path.stat().st_size if chunk_path.exists() else 0

            # Create chunk model
            chunk = VideoChunk(
                video_id=video_id,
                start_time=current_start,
                end_time=end_time,
                blob_path=str(chunk_path),
                thumbnail_path=str(thumb_path),
                width=1280,  # TODO: Get from video metadata
                height=720,
                fps=30.0,
                has_audio=True,
                size_bytes=size_bytes,
            )

            # Only include if within size limit
            if chunk.is_within_size_limit(max_size_mb):
                chunks.append(chunk)
            else:
                skipped_for_size += 1
                self._logger.debug(
                    "Video chunk skipped due to size limit",
                    extra={
                        "chunk_idx": chunk_idx,
                        "size_bytes": size_bytes,
                        "max_size_mb": max_size_mb,
                    },
                )

            chunk_idx += 1
            current_start = end_time - overlap_seconds
            current_start = max(current_start, 0)

        self._logger.info(
            "Video chunking completed",
            extra={
                "video_id": video_id,
                "chunks_created": len(chunks),
                "chunks_processed": chunk_idx,
                "skipped_for_size": skipped_for_size,
                "total_duration_seconds": chunks[-1].end_time if chunks else 0,
            },
        )

        return chunks

    async def chunk_all(
        self,
        video_path: Path,
        audio_path: Path,
        video_id: str,
        duration_seconds: float,
        transcription_segments: list[TranscriptionSegment],
        language: str,
        output_dir: Path,
        *,
        include_frames: bool = True,
        include_audio: bool = False,
        include_video: bool = False,
    ) -> ChunkingResult:
        """Create all chunk types for a video.

        Args:
            video_path: Path to video file.
            audio_path: Path to audio file.
            video_id: Parent video ID.
            duration_seconds: Total video duration.
            transcription_segments: Transcription segments.
            language: Detected language.
            output_dir: Base output directory.
            include_frames: Whether to extract frames.
            include_audio: Whether to create audio chunks.
            include_video: Whether to create video chunks.

        Returns:
            ChunkingResult with all created chunks.
        """
        self._logger.info(
            "Starting full chunking pipeline",
            extra={
                "video_id": video_id,
                "duration_seconds": duration_seconds,
                "language": language,
                "segment_count": len(transcription_segments),
                "include_frames": include_frames,
                "include_audio": include_audio,
                "include_video": include_video,
                "output_dir": str(output_dir),
            },
        )

        # Create subdirectories
        frames_dir = output_dir / "frames"
        audio_dir = output_dir / "audio"
        video_dir = output_dir / "video"

        frames_dir.mkdir(parents=True, exist_ok=True)
        audio_dir.mkdir(parents=True, exist_ok=True)
        video_dir.mkdir(parents=True, exist_ok=True)

        # Create transcript chunks (synchronous)
        self._logger.debug("Creating transcript chunks")
        transcript_chunks = self.create_transcript_chunks(
            segments=transcription_segments,
            video_id=video_id,
            language=language,
        )

        # Create other chunk types
        frame_chunks: list[FrameChunk] = []
        audio_chunks: list[AudioChunk] = []
        video_chunks: list[VideoChunk] = []

        if include_frames:
            self._logger.debug("Extracting frame chunks")
            frame_chunks = await self.extract_frame_chunks(
                video_path=video_path,
                video_id=video_id,
                duration_seconds=duration_seconds,
                output_dir=frames_dir,
            )

        if include_audio:
            self._logger.debug("Creating audio chunks")
            audio_chunks = await self.create_audio_chunks(
                audio_path=audio_path,
                video_id=video_id,
                duration_seconds=duration_seconds,
                output_dir=audio_dir,
            )

        if include_video:
            self._logger.debug("Creating video chunks")
            video_chunks = await self.create_video_chunks(
                video_path=video_path,
                video_id=video_id,
                duration_seconds=duration_seconds,
                output_dir=video_dir,
            )

        self._logger.info(
            "Full chunking pipeline completed",
            extra={
                "video_id": video_id,
                "transcript_chunks": len(transcript_chunks),
                "frame_chunks": len(frame_chunks),
                "audio_chunks": len(audio_chunks),
                "video_chunks": len(video_chunks),
                "total_chunks": (
                    len(transcript_chunks)
                    + len(frame_chunks)
                    + len(audio_chunks)
                    + len(video_chunks)
                ),
            },
        )

        return ChunkingResult(
            transcript_chunks=transcript_chunks,
            frame_chunks=frame_chunks,
            audio_chunks=audio_chunks,
            video_chunks=video_chunks,
        )
