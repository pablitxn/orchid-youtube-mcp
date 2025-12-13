"""FFmpeg implementation of video chunking."""

import asyncio
import json
import subprocess
from pathlib import Path

from src.commons.telemetry import get_logger
from src.infrastructure.video.base import (
    AudioSegment,
    VideoChunkerBase,
    VideoInfo,
    VideoSegment,
)


class FFmpegVideoChunker(VideoChunkerBase):
    """FFmpeg-based video chunking/segmentation.

    Requires ffmpeg and ffprobe to be installed and available in PATH.
    """

    def __init__(
        self,
        ffmpeg_path: str = "ffmpeg",
        ffprobe_path: str = "ffprobe",
    ) -> None:
        """Initialize FFmpeg video chunker.

        Args:
            ffmpeg_path: Path to ffmpeg executable.
            ffprobe_path: Path to ffprobe executable.
        """
        self._ffmpeg = ffmpeg_path
        self._ffprobe = ffprobe_path
        self._logger = get_logger(__name__)

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
        """Split video into chunks."""
        output_dir.mkdir(parents=True, exist_ok=True)
        video_info = await self.get_video_info(video_path)

        segments: list[VideoSegment] = []
        current_time = 0.0
        chunk_idx = 0

        while current_time < video_info.duration_seconds:
            chunk_idx += 1
            start_time = current_time
            end_time = min(
                start_time + chunk_seconds,
                video_info.duration_seconds,
            )

            output_path = output_dir / f"chunk_{chunk_idx:04d}.{format}"

            segment = await self.extract_segment(
                video_path=video_path,
                output_path=output_path,
                start_time=start_time,
                end_time=end_time,
                include_audio=include_audio,
            )

            # Check size and re-encode if needed
            if max_size_mb and segment.size_bytes > max_size_mb * 1024 * 1024:
                segment = await self._reencode_to_size(
                    video_path=video_path,
                    output_path=output_path,
                    start_time=start_time,
                    end_time=end_time,
                    max_size_mb=max_size_mb,
                    include_audio=include_audio,
                )

            segments.append(segment)

            # Move to next chunk with overlap
            current_time = end_time - overlap_seconds
            if current_time <= start_time:
                current_time = end_time

        return segments

    async def extract_segment(
        self,
        video_path: Path,
        output_path: Path,
        start_time: float,
        end_time: float,
        include_audio: bool = True,
    ) -> VideoSegment:
        """Extract a specific segment from video."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration = end_time - start_time

        cmd = [
            self._ffmpeg,
            "-ss",
            str(start_time),
            "-i",
            str(video_path),
            "-t",
            str(duration),
            "-c",
            "copy",  # Copy without re-encoding for speed
        ]

        if not include_audio:
            cmd.extend(["-an"])

        cmd.extend(["-y", str(output_path)])

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, check=True),
        )

        # Get output file size
        size_bytes = output_path.stat().st_size

        return VideoSegment(
            path=output_path,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            size_bytes=size_bytes,
            has_audio=include_audio,
        )

    async def extract_audio(
        self,
        video_path: Path,
        output_path: Path,
        format: str = "mp3",
        bitrate: str = "192k",
    ) -> Path:
        """Extract audio track from video."""
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            self._ffmpeg,
            "-i",
            str(video_path),
            "-vn",  # No video
            "-acodec",
            "libmp3lame" if format == "mp3" else "aac",
            "-ab",
            bitrate,
            "-y",
            str(output_path),
        ]

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, check=True),
        )

        return output_path

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

    async def chunk_by_scenes(
        self,
        video_path: Path,
        output_dir: Path,
        threshold: float = 0.3,
        min_scene_seconds: float = 2.0,
        max_scene_seconds: float = 60.0,
        format: str = "mp4",
    ) -> list[VideoSegment]:
        """Split video by scene detection."""
        output_dir.mkdir(parents=True, exist_ok=True)

        # Detect scene changes using ffprobe
        scene_times = await self._detect_scenes(video_path, threshold)

        # Get video duration
        video_info = await self.get_video_info(video_path)
        duration = video_info.duration_seconds

        # Build scene boundaries respecting min/max constraints
        boundaries: list[float] = [0.0]

        for scene_time in scene_times:
            last_boundary = boundaries[-1]

            # Skip if too close to last boundary
            if scene_time - last_boundary < min_scene_seconds:
                continue

            # Add intermediate boundaries if scene is too long
            while scene_time - last_boundary > max_scene_seconds:
                boundaries.append(last_boundary + max_scene_seconds)
                last_boundary = boundaries[-1]

            if scene_time - last_boundary >= min_scene_seconds:
                boundaries.append(scene_time)

        # Add final boundary
        if duration - boundaries[-1] > min_scene_seconds:
            boundaries.append(duration)

        # Extract segments
        segments: list[VideoSegment] = []
        for idx in range(len(boundaries) - 1):
            start_time = boundaries[idx]
            end_time = boundaries[idx + 1]

            output_path = output_dir / f"scene_{idx + 1:04d}.{format}"

            segment = await self.extract_segment(
                video_path=video_path,
                output_path=output_path,
                start_time=start_time,
                end_time=end_time,
                include_audio=True,
            )
            segments.append(segment)

        return segments

    async def _detect_scenes(
        self,
        video_path: Path,
        threshold: float,
    ) -> list[float]:
        """Detect scene changes in video."""
        cmd = [
            self._ffprobe,
            "-v",
            "quiet",
            "-show_entries",
            "frame=pkt_pts_time",
            "-of",
            "json",
            "-f",
            "lavfi",
            f"movie={video_path},select='gt(scene,{threshold})'",
        ]

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, check=True),
            )
            data = json.loads(result.stdout)

            times: list[float] = []
            for frame in data.get("frames", []):
                pts_time = frame.get("pkt_pts_time")
                if pts_time:
                    times.append(float(pts_time))
            return times
        except subprocess.CalledProcessError:
            # Scene detection failed, return empty list
            return []

    async def _reencode_to_size(
        self,
        video_path: Path,
        output_path: Path,
        start_time: float,
        end_time: float,
        max_size_mb: float,
        include_audio: bool,
    ) -> VideoSegment:
        """Re-encode segment to fit within size limit."""
        duration = end_time - start_time

        # Calculate target bitrate
        # max_size (bits) = bitrate (bits/s) * duration (s)
        max_size_bits = max_size_mb * 1024 * 1024 * 8
        audio_bitrate = 128000 if include_audio else 0  # 128kbps for audio
        video_bitrate = int((max_size_bits / duration) - audio_bitrate)
        video_bitrate = max(video_bitrate, 100000)  # Minimum 100kbps

        cmd = [
            self._ffmpeg,
            "-ss",
            str(start_time),
            "-i",
            str(video_path),
            "-t",
            str(duration),
            "-c:v",
            "libx264",
            "-b:v",
            str(video_bitrate),
            "-preset",
            "medium",
        ]

        if include_audio:
            cmd.extend(["-c:a", "aac", "-b:a", "128k"])
        else:
            cmd.append("-an")

        cmd.extend(["-y", str(output_path)])

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, check=True),
        )

        size_bytes = output_path.stat().st_size

        return VideoSegment(
            path=output_path,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            size_bytes=size_bytes,
            has_audio=include_audio,
        )

    async def chunk_audio(
        self,
        audio_path: Path,
        output_dir: Path,
        chunk_seconds: int = 60,
        format: str = "mp3",
        bitrate: str = "192k",
    ) -> list[AudioSegment]:
        """Split audio into chunks."""
        self._logger.debug(
            "Starting audio chunking",
            extra={
                "audio_path": str(audio_path),
                "output_dir": str(output_dir),
                "chunk_seconds": chunk_seconds,
                "format": format,
            },
        )
        output_dir.mkdir(parents=True, exist_ok=True)

        # Get audio duration using ffprobe
        duration = await self._get_audio_duration(audio_path)

        self._logger.debug(
            "Audio duration retrieved",
            extra={"duration": duration, "audio_path": str(audio_path)},
        )

        if duration <= 0:
            self._logger.warning(
                "Audio duration is zero or negative, no chunks will be created",
                extra={"duration": duration, "audio_path": str(audio_path)},
            )
            return []

        segments: list[AudioSegment] = []
        current_time = 0.0
        chunk_idx = 0
        expected_chunks = int(duration // chunk_seconds) + 1

        self._logger.debug(
            "Will create audio chunks",
            extra={"expected_chunks": expected_chunks, "duration": duration},
        )

        while current_time < duration:
            chunk_idx += 1
            start_time = current_time
            end_time = min(start_time + chunk_seconds, duration)

            output_path = output_dir / f"audio_{chunk_idx:04d}.{format}"

            segment = await self.extract_audio_segment(
                audio_path=audio_path,
                output_path=output_path,
                start_time=start_time,
                end_time=end_time,
                format=format,
                bitrate=bitrate,
            )
            segments.append(segment)

            current_time = end_time

        self._logger.debug(
            "Audio chunking complete",
            extra={"total_chunks": len(segments)},
        )

        return segments

    async def extract_audio_segment(
        self,
        audio_path: Path,
        output_path: Path,
        start_time: float,
        end_time: float,
        format: str = "mp3",
        bitrate: str = "192k",
    ) -> AudioSegment:
        """Extract a specific segment from audio."""
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration = end_time - start_time

        # Determine codec based on format
        codec_map = {
            "mp3": "libmp3lame",
            "aac": "aac",
            "wav": "pcm_s16le",
            "flac": "flac",
            "ogg": "libvorbis",
        }
        codec = codec_map.get(format, "libmp3lame")

        cmd = [
            self._ffmpeg,
            "-ss",
            str(start_time),
            "-i",
            str(audio_path),
            "-t",
            str(duration),
            "-acodec",
            codec,
        ]

        # Add bitrate for lossy formats
        if format in ("mp3", "aac", "ogg"):
            cmd.extend(["-ab", bitrate])

        cmd.extend(["-y", str(output_path)])

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, check=True),
        )

        size_bytes = output_path.stat().st_size

        return AudioSegment(
            path=output_path,
            start_time=start_time,
            end_time=end_time,
            duration=duration,
            size_bytes=size_bytes,
            format=format,
        )

    async def _get_audio_duration(self, audio_path: Path) -> float:
        """Get duration of an audio file using ffprobe."""
        cmd = [
            self._ffprobe,
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(audio_path),
        ]

        self._logger.debug(
            "Getting audio duration with ffprobe",
            extra={"audio_path": str(audio_path), "command": " ".join(cmd)},
        )

        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(cmd, capture_output=True, check=True),
            )
        except subprocess.CalledProcessError as e:
            self._logger.error(
                "ffprobe failed to get audio duration",
                extra={
                    "audio_path": str(audio_path),
                    "stderr": e.stderr.decode() if e.stderr else None,
                    "returncode": e.returncode,
                },
            )
            return 0.0

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            self._logger.error(
                "Failed to parse ffprobe JSON output",
                extra={
                    "audio_path": str(audio_path),
                    "stdout": result.stdout.decode() if result.stdout else None,
                    "error": str(e),
                },
            )
            return 0.0

        duration = float(data.get("format", {}).get("duration", 0))

        if duration <= 0:
            self._logger.warning(
                "ffprobe returned zero or invalid duration",
                extra={
                    "audio_path": str(audio_path),
                    "ffprobe_data": data,
                },
            )

        return duration
