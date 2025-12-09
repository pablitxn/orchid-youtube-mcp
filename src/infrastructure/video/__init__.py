"""Video processing services."""

from src.infrastructure.video.base import (
    ExtractedFrame,
    FrameExtractorBase,
    VideoChunkerBase,
    VideoInfo,
    VideoSegment,
)
from src.infrastructure.video.ffmpeg_chunker import FFmpegVideoChunker
from src.infrastructure.video.ffmpeg_extractor import FFmpegFrameExtractor

__all__ = [
    # Base classes
    "FrameExtractorBase",
    "VideoChunkerBase",
    "VideoInfo",
    "ExtractedFrame",
    "VideoSegment",
    # Implementations
    "FFmpegFrameExtractor",
    "FFmpegVideoChunker",
]
