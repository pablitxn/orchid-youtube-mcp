"""Abstract base classes for video processing services."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class VideoInfo:
    """Information about a video file."""

    path: Path
    duration_seconds: float
    width: int
    height: int
    fps: float
    codec: str
    bitrate: int
    has_audio: bool
    audio_codec: str | None
    file_size_bytes: int


@dataclass
class ExtractedFrame:
    """A frame extracted from video."""

    path: Path
    thumbnail_path: Path | None
    frame_number: int
    timestamp: float
    width: int
    height: int


@dataclass
class VideoSegment:
    """A segment/chunk of video."""

    path: Path
    start_time: float
    end_time: float
    duration: float
    size_bytes: int
    has_audio: bool


@dataclass
class AudioSegment:
    """A segment/chunk of audio."""

    path: Path
    start_time: float
    end_time: float
    duration: float
    size_bytes: int
    format: str
    sample_rate: int = 44100
    channels: int = 2


class FrameExtractorBase(ABC):
    """Abstract base class for video frame extraction.

    Implementations should handle:
    - FFmpeg (via ffmpeg-python)
    - MoviePy
    - OpenCV
    """

    @abstractmethod
    async def extract_frames(
        self,
        video_path: Path,
        output_dir: Path,
        interval_seconds: float = 2.0,
        format: str = "jpg",
        quality: int = 85,
        max_dimension: int | None = 1920,
        thumbnail_size: tuple[int, int] | None = (320, 180),
    ) -> list[ExtractedFrame]:
        """Extract frames at regular intervals.

        Args:
            video_path: Path to input video.
            output_dir: Directory to save frames.
            interval_seconds: Time between frames.
            format: Output image format (jpg, png, webp).
            quality: JPEG quality (1-100).
            max_dimension: Max width/height, None for original.
            thumbnail_size: Size for thumbnails, None to skip.

        Returns:
            List of extracted frames with metadata.
        """

    @abstractmethod
    async def extract_frame_at(
        self,
        video_path: Path,
        timestamp: float,
        output_path: Path,
        max_dimension: int | None = None,
    ) -> ExtractedFrame:
        """Extract a single frame at specific timestamp.

        Args:
            video_path: Path to input video.
            timestamp: Time in seconds.
            output_path: Where to save the frame.
            max_dimension: Max width/height, None for original.

        Returns:
            Extracted frame metadata.
        """

    @abstractmethod
    async def extract_keyframes(
        self,
        video_path: Path,
        output_dir: Path,
        format: str = "jpg",
        quality: int = 85,
    ) -> list[ExtractedFrame]:
        """Extract only keyframes (I-frames) from video.

        Args:
            video_path: Path to input video.
            output_dir: Directory to save frames.
            format: Output image format.
            quality: JPEG quality.

        Returns:
            List of keyframes with metadata.
        """

    @abstractmethod
    async def get_video_info(self, video_path: Path) -> VideoInfo:
        """Get detailed video information.

        Args:
            video_path: Path to video file.

        Returns:
            Video metadata.
        """


class VideoChunkerBase(ABC):
    """Abstract base class for video chunking/segmentation.

    Implementations should handle:
    - FFmpeg (via ffmpeg-python)
    - MoviePy
    """

    @abstractmethod
    async def chunk_video(
        self,
        video_path: Path,
        output_dir: Path,
        chunk_seconds: int = 30,
        overlap_seconds: int = 2,
        max_size_mb: float | None = 20.0,
        format: str = "mp4",
        include_audio: bool = True,
    ) -> list[VideoSegment]:
        """Split video into chunks.

        Args:
            video_path: Path to input video.
            output_dir: Directory to save chunks.
            chunk_seconds: Target chunk duration.
            overlap_seconds: Overlap between chunks.
            max_size_mb: Maximum chunk size, None for no limit.
            format: Output video format.
            include_audio: Whether to include audio track.

        Returns:
            List of video segments with metadata.
        """

    @abstractmethod
    async def extract_segment(
        self,
        video_path: Path,
        output_path: Path,
        start_time: float,
        end_time: float,
        include_audio: bool = True,
    ) -> VideoSegment:
        """Extract a specific segment from video.

        Args:
            video_path: Path to input video.
            output_path: Where to save the segment.
            start_time: Start time in seconds.
            end_time: End time in seconds.
            include_audio: Whether to include audio track.

        Returns:
            Video segment metadata.
        """

    @abstractmethod
    async def extract_audio(
        self,
        video_path: Path,
        output_path: Path,
        format: str = "mp3",
        bitrate: str = "192k",
    ) -> Path:
        """Extract audio track from video.

        Args:
            video_path: Path to input video.
            output_path: Where to save audio.
            format: Output audio format.
            bitrate: Audio bitrate.

        Returns:
            Path to extracted audio.
        """

    @abstractmethod
    async def get_video_info(self, video_path: Path) -> VideoInfo:
        """Get detailed video information.

        Args:
            video_path: Path to video file.

        Returns:
            Video metadata.
        """

    @abstractmethod
    async def chunk_by_scenes(
        self,
        video_path: Path,
        output_dir: Path,
        threshold: float = 0.3,
        min_scene_seconds: float = 2.0,
        max_scene_seconds: float = 60.0,
        format: str = "mp4",
    ) -> list[VideoSegment]:
        """Split video by scene detection.

        Args:
            video_path: Path to input video.
            output_dir: Directory to save chunks.
            threshold: Scene change detection threshold (0-1).
            min_scene_seconds: Minimum scene duration.
            max_scene_seconds: Maximum scene duration.
            format: Output video format.

        Returns:
            List of video segments at scene boundaries.
        """

    @abstractmethod
    async def chunk_audio(
        self,
        audio_path: Path,
        output_dir: Path,
        chunk_seconds: int = 60,
        format: str = "mp3",
        bitrate: str = "192k",
    ) -> list[AudioSegment]:
        """Split audio into chunks.

        Args:
            audio_path: Path to input audio file.
            output_dir: Directory to save audio chunks.
            chunk_seconds: Target chunk duration in seconds.
            format: Output audio format (mp3, wav, etc.).
            bitrate: Audio bitrate.

        Returns:
            List of audio segments with metadata.
        """

    @abstractmethod
    async def extract_audio_segment(
        self,
        audio_path: Path,
        output_path: Path,
        start_time: float,
        end_time: float,
        format: str = "mp3",
        bitrate: str = "192k",
    ) -> AudioSegment:
        """Extract a specific segment from audio.

        Args:
            audio_path: Path to input audio file.
            output_path: Where to save the segment.
            start_time: Start time in seconds.
            end_time: End time in seconds.
            format: Output audio format.
            bitrate: Audio bitrate.

        Returns:
            Audio segment metadata.
        """
