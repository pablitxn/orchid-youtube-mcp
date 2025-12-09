"""FFmpeg implementation of frame extraction."""

import asyncio
import json
import subprocess
from pathlib import Path

from PIL import Image

from src.infrastructure.video.base import (
    ExtractedFrame,
    FrameExtractorBase,
    VideoInfo,
)


class FFmpegFrameExtractor(FrameExtractorBase):
    """FFmpeg-based frame extraction from video files.

    Requires ffmpeg and ffprobe to be installed and available in PATH.
    """

    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
    ) -> None:
        """Initialize FFmpeg frame extractor.

        Args:
            ffmpeg_path: Path to ffmpeg executable.
            ffprobe_path: Path to ffprobe executable.
        """
        self._ffmpeg = ffmpeg_path
        self._ffprobe = ffprobe_path

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
        """Extract frames at regular intervals."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # Calculate fps for frame extraction
        fps = 1.0 / interval_seconds

        # Build scale filter
        scale_filter = ""
        if max_dimension:
            scale_filter = (
                f",scale='min({max_dimension},iw)'"
                f":min'({max_dimension},ih)':force_original_aspect_ratio=decrease"
            )

        # Extract frames using ffmpeg
        output_pattern = str(output_dir / f"frame_%05d.{format}")

        cmd = [
            self._ffmpeg,
            "-i",
            str(video_path),
            "-vf",
            f"fps={fps}{scale_filter}",
            "-q:v",
            str(int((100 - quality) / 100 * 31)),  # Convert quality to ffmpeg scale
            "-y",
            output_pattern,
        ]

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, check=True),
        )

        # Find all extracted frames and build metadata
        frames: list[ExtractedFrame] = []
        frame_files = sorted(output_dir.glob(f"frame_*.{format}"))

        for idx, frame_path in enumerate(frame_files):
            frame_number = idx + 1
            timestamp = idx * interval_seconds

            # Get frame dimensions
            with Image.open(frame_path) as img:
                width, height = img.size

            # Create thumbnail if requested
            thumbnail_path = None
            if thumbnail_size:
                thumbnail_path = output_dir / f"thumb_{frame_number:05d}.{format}"
                await self._create_thumbnail(
                    frame_path, thumbnail_path, thumbnail_size, quality
                )

            frames.append(
                ExtractedFrame(
                    path=frame_path,
                    thumbnail_path=thumbnail_path,
                    frame_number=frame_number,
                    timestamp=timestamp,
                    width=width,
                    height=height,
                )
            )

        return frames

    async def extract_frame_at(
        self,
        video_path: Path,
        timestamp: float,
        output_path: Path,
        max_dimension: int | None = None,
    ) -> ExtractedFrame:
        """Extract a single frame at specific timestamp."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self._ffmpeg,
            "-ss",
            str(timestamp),
            "-i",
            str(video_path),
            "-vframes",
            "1",
        ]

        if max_dimension:
            scale_filter = (
                f"scale='min({max_dimension},iw)'"
                f":min'({max_dimension},ih)':force_original_aspect_ratio=decrease"
            )
            cmd.extend(["-vf", scale_filter])

        cmd.extend(["-y", str(output_path)])

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, check=True),
        )

        # Get frame dimensions
        with Image.open(output_path) as img:
            width, height = img.size

        return ExtractedFrame(
            path=output_path,
            thumbnail_path=None,
            frame_number=1,
            timestamp=timestamp,
            width=width,
            height=height,
        )

    async def extract_keyframes(
        self,
        video_path: Path,
        output_dir: Path,
        format: str = "jpg",
        quality: int = 85,
    ) -> list[ExtractedFrame]:
        """Extract only keyframes (I-frames) from video."""
        output_dir.mkdir(parents=True, exist_ok=True)

        output_pattern = str(output_dir / f"keyframe_%05d.{format}")

        cmd = [
            self._ffmpeg,
            "-i",
            str(video_path),
            "-vf",
            "select='eq(pict_type,I)'",
            "-vsync",
            "vfr",
            "-q:v",
            str(int((100 - quality) / 100 * 31)),
            "-y",
            output_pattern,
        ]

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, check=True),
        )

        # Get keyframe timestamps using ffprobe
        keyframe_times = await self._get_keyframe_timestamps(video_path)

        frames: list[ExtractedFrame] = []
        frame_files = sorted(output_dir.glob(f"keyframe_*.{format}"))

        for idx, frame_path in enumerate(frame_files):
            with Image.open(frame_path) as img:
                width, height = img.size

            timestamp = keyframe_times[idx] if idx < len(keyframe_times) else 0.0

            frames.append(
                ExtractedFrame(
                    path=frame_path,
                    thumbnail_path=None,
                    frame_number=idx + 1,
                    timestamp=timestamp,
                    width=width,
                    height=height,
                )
            )

        return frames

    async def get_video_info(self, video_path: Path) -> VideoInfo:
        """Get detailed video information."""
        cmd = [
            self._ffprobe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(video_path),
        ]

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, check=True),
        )

        data = json.loads(result.stdout)

        # Find video stream
        video_stream = None
        audio_stream = None
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and video_stream is None:
                video_stream = stream
            elif stream.get("codec_type") == "audio" and audio_stream is None:
                audio_stream = stream

        if not video_stream:
            raise ValueError(f"No video stream found in {video_path}")

        format_info = data.get("format", {})

        # Parse fps from frame rate fraction
        fps_str = video_stream.get("r_frame_rate", "30/1")
        if "/" in fps_str:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) != 0 else 30.0
        else:
            fps = float(fps_str)

        return VideoInfo(
            path=video_path,
            duration_seconds=float(format_info.get("duration", 0)),
            width=int(video_stream.get("width", 0)),
            height=int(video_stream.get("height", 0)),
            fps=fps,
            codec=video_stream.get("codec_name", "unknown"),
            bitrate=int(format_info.get("bit_rate", 0)),
            has_audio=audio_stream is not None,
            audio_codec=audio_stream.get("codec_name") if audio_stream else None,
            file_size_bytes=int(format_info.get("size", 0)),
        )

    async def _create_thumbnail(
        self,
        source_path: Path,
        output_path: Path,
        size: tuple[int, int],
        quality: int,
    ) -> None:
        """Create a thumbnail from an image."""
        loop = asyncio.get_event_loop()

        def _resize() -> None:
            with Image.open(source_path) as img:
                img.thumbnail(size, Image.Resampling.LANCZOS)
                img.save(output_path, quality=quality)

        await loop.run_in_executor(None, _resize)

    async def _get_keyframe_timestamps(self, video_path: Path) -> list[float]:
        """Get timestamps of all keyframes in the video."""
        cmd = [
            self._ffprobe,
            "-v",
            "quiet",
            "-select_streams",
            "v:0",
            "-show_entries",
            "frame=pkt_pts_time,pict_type",
            "-of",
            "json",
            str(video_path),
        ]

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, check=True),
        )

        data = json.loads(result.stdout)
        timestamps: list[float] = []

        for frame in data.get("frames", []):
            if frame.get("pict_type") == "I":
                pts_time = frame.get("pkt_pts_time")
                if pts_time:
                    timestamps.append(float(pts_time))

        return timestamps
