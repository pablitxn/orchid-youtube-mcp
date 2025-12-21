"""yt-dlp implementation of YouTube downloader."""

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import yt_dlp

from src.infrastructure.youtube.base import (
    DownloadResult,
    SubtitleTrack,
    YouTubeDownloaderBase,
    YouTubeMetadata,
)


class VideoNotFoundError(Exception):
    """Raised when a video is not found."""

    def __init__(self, url: str) -> None:
        self.url = url
        super().__init__(f"Video not found: {url}")


class DownloadError(Exception):
    """Raised when download fails."""

    def __init__(self, url: str, reason: str) -> None:
        self.url = url
        self.reason = reason
        super().__init__(f"Download failed for {url}: {reason}")


class YtDlpDownloader(YouTubeDownloaderBase):
    """yt-dlp implementation of YouTube downloader."""

    # YouTube URL patterns
    _URL_PATTERNS: ClassVar[list[str]] = [
        r"^https?://(?:www\.)?youtube\.com/watch\?v=[\w-]+",
        r"^https?://(?:www\.)?youtube\.com/shorts/[\w-]+",
        r"^https?://youtu\.be/[\w-]+",
        r"^https?://(?:www\.)?youtube\.com/embed/[\w-]+",
        r"^https?://(?:www\.)?youtube\.com/v/[\w-]+",
    ]
    _VIDEO_ID_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:v=|/(?:shorts/|embed/|v/)|youtu\.be/)([\w-]{11})"
    )

    def __init__(
        self,
        cookies_file: Path | None = None,
        cookies_from_browser: str | None = None,
        proxy: str | None = None,
        rate_limit: str | None = None,
    ) -> None:
        """Initialize yt-dlp downloader.

        Args:
            cookies_file: Path to cookies file for authenticated downloads.
            cookies_from_browser: Browser name to extract cookies from
                (e.g., "chrome", "firefox", "edge", "safari", "opera", "brave").
            proxy: Proxy URL.
            rate_limit: Rate limit (e.g., "50K", "1M").
        """
        self._cookies_file = cookies_file
        self._cookies_from_browser = cookies_from_browser
        self._proxy = proxy
        self._rate_limit = rate_limit

    def _get_base_opts(self) -> dict[str, Any]:
        """Get base yt-dlp options."""
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "extract_flat": False,
        }

        # Cookie authentication (file takes precedence over browser)
        if self._cookies_file:
            opts["cookiefile"] = str(self._cookies_file)
        elif self._cookies_from_browser:
            opts["cookiesfrombrowser"] = (self._cookies_from_browser,)
        if self._proxy:
            opts["proxy"] = self._proxy
        if self._rate_limit:
            opts["ratelimit"] = self._rate_limit

        return opts

    async def download(
        self,
        url: str,
        output_dir: Path,
        video_format: str = "mp4",
        audio_format: str = "mp3",
        max_resolution: int = 1080,
    ) -> DownloadResult:
        """Download video and extract audio."""
        loop = asyncio.get_event_loop()
        output_dir.mkdir(parents=True, exist_ok=True)

        # First get metadata
        metadata = await self.get_metadata(url)
        video_id = metadata.id

        video_path = output_dir / f"{video_id}.{video_format}"
        audio_path = output_dir / f"{video_id}.{audio_format}"

        # Download video
        video_opts = self._get_base_opts()
        format_spec = (
            f"bestvideo[height<={max_resolution}]+bestaudio"
            f"/best[height<={max_resolution}]"
        )
        video_opts.update(
            {
                "format": format_spec,
                "outtmpl": str(output_dir / f"{video_id}.%(ext)s"),
                "merge_output_format": video_format,
            }
        )

        def _download_video() -> dict[str, Any]:
            with yt_dlp.YoutubeDL(video_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    raise VideoNotFoundError(url)
                return dict(info)

        try:
            format_info = await loop.run_in_executor(None, _download_video)
        except yt_dlp.DownloadError as e:
            raise DownloadError(url, str(e)) from e

        # Extract audio
        # Use %(ext)s so yt-dlp handles extensions correctly during conversion
        # FFmpegExtractAudio will download in original format then convert to target
        audio_opts = self._get_base_opts()
        audio_opts.update(
            {
                "format": "bestaudio/best",
                "outtmpl": str(output_dir / f"{video_id}.%(ext)s"),
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": audio_format,
                        "preferredquality": "192",
                    }
                ],
            }
        )

        def _extract_audio() -> None:
            with yt_dlp.YoutubeDL(audio_opts) as ydl:
                ydl.extract_info(url, download=True)

        try:
            await loop.run_in_executor(None, _extract_audio)
        except yt_dlp.DownloadError as e:
            raise DownloadError(url, f"Audio extraction failed: {e}") from e

        return DownloadResult(
            video_path=video_path,
            audio_path=audio_path,
            metadata=metadata,
            format_info=format_info,
        )

    async def download_audio_only(
        self,
        url: str,
        output_dir: Path,
        audio_format: str = "mp3",
        audio_quality: str = "192",
    ) -> tuple[Path, YouTubeMetadata]:
        """Download only the audio track."""
        loop = asyncio.get_event_loop()
        output_dir.mkdir(parents=True, exist_ok=True)

        metadata = await self.get_metadata(url)
        video_id = metadata.id
        audio_path = output_dir / f"{video_id}.{audio_format}"

        # Use %(ext)s so yt-dlp handles extensions correctly during conversion
        opts = self._get_base_opts()
        opts.update(
            {
                "format": "bestaudio/best",
                "outtmpl": str(output_dir / f"{video_id}.%(ext)s"),
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": audio_format,
                        "preferredquality": audio_quality,
                    }
                ],
            }
        )

        def _download() -> None:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.extract_info(url, download=True)

        try:
            await loop.run_in_executor(None, _download)
        except yt_dlp.DownloadError as e:
            raise DownloadError(url, str(e)) from e

        # After FFmpegExtractAudio, the file will have the target extension
        return audio_path, metadata

    async def get_metadata(self, url: str) -> YouTubeMetadata:
        """Get video metadata without downloading."""
        loop = asyncio.get_event_loop()

        opts = self._get_base_opts()
        opts["skip_download"] = True

        def _extract() -> dict[str, Any]:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    raise VideoNotFoundError(url)
                return dict(info)

        try:
            info = await loop.run_in_executor(None, _extract)
        except yt_dlp.DownloadError as e:
            if "Video unavailable" in str(e) or "Private video" in str(e):
                raise VideoNotFoundError(url) from e
            raise DownloadError(url, str(e)) from e

        # Parse upload date
        upload_date_str = info.get("upload_date", "")
        if upload_date_str:
            upload_date = datetime.strptime(upload_date_str, "%Y%m%d").replace(
                tzinfo=UTC
            )
        else:
            upload_date = datetime.now(UTC)

        return YouTubeMetadata(
            id=info.get("id", ""),
            title=info.get("title", ""),
            description=info.get("description", ""),
            duration_seconds=info.get("duration", 0),
            channel_name=info.get("channel", "") or info.get("uploader", ""),
            channel_id=info.get("channel_id", ""),
            upload_date=upload_date,
            thumbnail_url=info.get("thumbnail", ""),
            view_count=info.get("view_count", 0),
            like_count=info.get("like_count"),
            tags=info.get("tags", []) or [],
            categories=info.get("categories", []) or [],
        )

    async def get_subtitles(
        self,
        url: str,
        languages: list[str] | None = None,
        include_auto_generated: bool = True,
    ) -> list[SubtitleTrack]:
        """Get available subtitles/captions."""
        loop = asyncio.get_event_loop()

        opts = self._get_base_opts()
        opts.update(
            {
                "skip_download": True,
                "writesubtitles": True,
                "writeautomaticsub": include_auto_generated,
                "subtitleslangs": languages or ["all"],
            }
        )

        def _extract() -> dict[str, Any]:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    raise VideoNotFoundError(url)
                return dict(info)

        try:
            info = await loop.run_in_executor(None, _extract)
        except yt_dlp.DownloadError as e:
            raise DownloadError(url, str(e)) from e

        subtitles: list[SubtitleTrack] = []

        # Manual subtitles
        for lang, subs in (info.get("subtitles") or {}).items():
            if languages and lang not in languages:
                continue
            for sub in subs:
                if sub.get("ext") in ("vtt", "srt", "json3"):
                    subtitles.append(
                        SubtitleTrack(
                            language=lang,
                            language_name=sub.get("name", lang),
                            content="",  # Would need separate download
                            is_auto_generated=False,
                        )
                    )
                    break

        # Auto-generated subtitles
        if include_auto_generated:
            for lang, subs in (info.get("automatic_captions") or {}).items():
                if languages and lang not in languages:
                    continue
                for sub in subs:
                    if sub.get("ext") in ("vtt", "srt", "json3"):
                        subtitles.append(
                            SubtitleTrack(
                                language=lang,
                                language_name=sub.get("name", lang),
                                content="",
                                is_auto_generated=True,
                            )
                        )
                        break

        return subtitles

    async def get_available_formats(self, url: str) -> list[dict[str, Any]]:
        """Get available video/audio formats."""
        loop = asyncio.get_event_loop()

        opts = self._get_base_opts()
        opts["skip_download"] = True

        def _extract() -> list[dict[str, Any]]:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if info is None:
                    raise VideoNotFoundError(url)
                return list(info.get("formats", []))

        try:
            formats = await loop.run_in_executor(None, _extract)
        except yt_dlp.DownloadError as e:
            raise DownloadError(url, str(e)) from e

        return [
            {
                "format_id": f.get("format_id"),
                "ext": f.get("ext"),
                "resolution": f.get("resolution"),
                "height": f.get("height"),
                "width": f.get("width"),
                "fps": f.get("fps"),
                "vcodec": f.get("vcodec"),
                "acodec": f.get("acodec"),
                "abr": f.get("abr"),
                "vbr": f.get("vbr"),
                "filesize": f.get("filesize") or f.get("filesize_approx"),
            }
            for f in formats
        ]

    def validate_url(self, url: str) -> bool:
        """Validate if URL is a valid YouTube video URL."""
        return any(re.match(pattern, url) for pattern in self._URL_PATTERNS)

    def extract_video_id(self, url: str) -> str | None:
        """Extract video ID from URL."""
        match = self._VIDEO_ID_PATTERN.search(url)
        return match.group(1) if match else None

    @property
    def supported_url_patterns(self) -> list[str]:
        """URL patterns supported by this downloader."""
        return self._URL_PATTERNS.copy()
