"""yt-dlp implementation of YouTube downloader."""

import asyncio
import re
import shutil
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

    def __init__(
        self,
        url: str,
        reason: str,
        *,
        code: str = "YOUTUBE_DOWNLOAD_FAILED",
        status_code: int = 502,
        kind: str = "download_failed",
        details: dict[str, str] | None = None,
        raw_reason: str | None = None,
    ) -> None:
        self.url = url
        self.reason = reason
        self.code = code
        self.status_code = status_code
        self.kind = kind
        self.details = {"kind": kind, **(details or {})}
        self.raw_reason = raw_reason or reason
        super().__init__(f"Download failed for {url}: {reason}")


class _YtDlpLogCollector:
    """Capture non-progress yt-dlp warnings/errors for classification."""

    def __init__(self) -> None:
        self.messages: list[str] = []

    def debug(self, message: str) -> None:
        """Ignore debug output to keep diagnostics focused."""

    def warning(self, message: str) -> None:
        """Capture warnings emitted by yt-dlp extractors."""
        self.messages.append(str(message))

    def error(self, message: str) -> None:
        """Capture errors emitted by yt-dlp."""
        self.messages.append(str(message))


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
    _AUTH_COOKIE_ROTATED_MARKERS: ClassVar[tuple[str, ...]] = (
        "cookies are no longer valid",
    )
    _AUTH_REQUIRED_MARKERS: ClassVar[tuple[str, ...]] = (
        "sign in to confirm you're not a bot",
        "sign in to confirm you\u2019re not a bot",
        "login_required",
    )
    _CHALLENGE_FAILURE_MARKERS: ClassVar[tuple[str, ...]] = (
        "n challenge solving failed",
        "no supported javascript runtime",
        "js runtimes: none",
        "js challenge providers",
    )
    _STREAM_FORBIDDEN_MARKERS: ClassVar[tuple[str, ...]] = (
        "http error 403: forbidden",
        "fragment not found",
    )
    _EMPTY_FILE_MARKERS: ClassVar[tuple[str, ...]] = ("downloaded file is empty",)

    def __init__(
        self,
        cookies_file: Path | None = None,
        proxy: str | None = None,
        rate_limit: str | None = None,
    ) -> None:
        """Initialize yt-dlp downloader.

        Args:
            cookies_file: Path to cookies file for authenticated downloads.
            proxy: Proxy URL.
            rate_limit: Rate limit (e.g., "50K", "1M").
        """
        self._cookies_file = cookies_file
        self._proxy = proxy
        self._rate_limit = rate_limit
        self._node_path = shutil.which("node")

    def configure_auth(
        self,
        *,
        cookies_file: Path | None,
    ) -> None:
        """Update auth configuration without recreating the downloader."""
        self._cookies_file = cookies_file

    def _get_base_opts(self) -> dict[str, Any]:
        """Get base yt-dlp options."""
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": False,
            "extract_flat": False,
        }

        if self._node_path:
            opts["js_runtimes"] = {"node": {"path": self._node_path}}

        # Managed cookie authentication
        if self._cookies_file:
            opts["cookiefile"] = str(self._cookies_file)
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
            collector = _YtDlpLogCollector()
            with yt_dlp.YoutubeDL({**video_opts, "logger": collector}) as ydl:
                try:
                    info = ydl.extract_info(url, download=True)
                except yt_dlp.DownloadError as exc:
                    raise self._classify_download_error(
                        url,
                        str(exc),
                        diagnostics=collector.messages,
                    ) from exc

                if info is None:
                    raise VideoNotFoundError(url)

                self._ensure_nonempty_file(
                    video_path,
                    url,
                    diagnostics=collector.messages,
                )
                return dict(info)

        format_info = await loop.run_in_executor(None, _download_video)

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
            collector = _YtDlpLogCollector()
            with yt_dlp.YoutubeDL({**audio_opts, "logger": collector}) as ydl:
                try:
                    ydl.extract_info(url, download=True)
                except yt_dlp.DownloadError as exc:
                    raise self._classify_download_error(
                        url,
                        f"Audio extraction failed: {exc}",
                        diagnostics=collector.messages,
                    ) from exc

                self._ensure_nonempty_file(
                    audio_path,
                    url,
                    diagnostics=collector.messages,
                )

        await loop.run_in_executor(None, _extract_audio)

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
            collector = _YtDlpLogCollector()
            with yt_dlp.YoutubeDL({**opts, "logger": collector}) as ydl:
                try:
                    ydl.extract_info(url, download=True)
                except yt_dlp.DownloadError as exc:
                    raise self._classify_download_error(
                        url,
                        str(exc),
                        diagnostics=collector.messages,
                    ) from exc

                self._ensure_nonempty_file(
                    audio_path,
                    url,
                    diagnostics=collector.messages,
                )

        await loop.run_in_executor(None, _download)

        # After FFmpegExtractAudio, the file will have the target extension
        return audio_path, metadata

    async def get_metadata(self, url: str) -> YouTubeMetadata:
        """Get video metadata without downloading."""
        loop = asyncio.get_event_loop()

        opts = self._get_base_opts()
        opts["skip_download"] = True

        def _extract() -> dict[str, Any]:
            collector = _YtDlpLogCollector()
            with yt_dlp.YoutubeDL({**opts, "logger": collector}) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                except yt_dlp.DownloadError as exc:
                    raw_reason = str(exc)
                    if (
                        "Video unavailable" in raw_reason
                        or "Private video" in raw_reason
                    ):
                        raise VideoNotFoundError(url) from exc
                    raise self._classify_download_error(
                        url,
                        raw_reason,
                        diagnostics=collector.messages,
                    ) from exc

                if info is None:
                    raise VideoNotFoundError(url)
                return dict(info)

        info = await loop.run_in_executor(None, _extract)

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
            collector = _YtDlpLogCollector()
            with yt_dlp.YoutubeDL({**opts, "logger": collector}) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                except yt_dlp.DownloadError as exc:
                    raise self._classify_download_error(
                        url,
                        str(exc),
                        diagnostics=collector.messages,
                    ) from exc

                if info is None:
                    raise VideoNotFoundError(url)
                return dict(info)

        info = await loop.run_in_executor(None, _extract)

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
            collector = _YtDlpLogCollector()
            with yt_dlp.YoutubeDL({**opts, "logger": collector}) as ydl:
                try:
                    info = ydl.extract_info(url, download=False)
                except yt_dlp.DownloadError as exc:
                    raise self._classify_download_error(
                        url,
                        str(exc),
                        diagnostics=collector.messages,
                    ) from exc

                if info is None:
                    raise VideoNotFoundError(url)
                return list(info.get("formats", []))

        formats = await loop.run_in_executor(None, _extract)

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

    def _ensure_nonempty_file(
        self,
        path: Path,
        url: str,
        *,
        diagnostics: list[str] | None = None,
    ) -> None:
        """Fail fast when yt-dlp leaves behind an empty artifact."""
        if path.exists() and path.stat().st_size > 0:
            return
        raise self._classify_download_error(
            url,
            "ERROR: The downloaded file is empty",
            diagnostics=diagnostics,
        )

    def _classify_download_error(
        self,
        url: str,
        raw_reason: str,
        *,
        diagnostics: list[str] | None = None,
    ) -> DownloadError:
        """Map yt-dlp failures to actionable API-level errors."""
        combined = "\n".join([raw_reason, *(diagnostics or [])]).casefold()

        if any(marker in combined for marker in self._AUTH_COOKIE_ROTATED_MARKERS):
            return DownloadError(
                url,
                (
                    "YouTube rejected the managed cookies.txt as expired or rotated. "
                    "Export a fresh cookies.txt from the browser, save it again, "
                    "and retry."
                ),
                code="YOUTUBE_AUTH_INVALID",
                status_code=409,
                kind="auth_invalid",
                raw_reason=raw_reason,
            )

        if any(marker in combined for marker in self._AUTH_REQUIRED_MARKERS):
            return DownloadError(
                url,
                (
                    "This video requires a valid logged-in YouTube session. "
                    "Save a fresh cookies.txt and retry."
                ),
                code="YOUTUBE_AUTH_REQUIRED",
                status_code=409,
                kind="auth_required",
                raw_reason=raw_reason,
            )

        if any(marker in combined for marker in self._CHALLENGE_FAILURE_MARKERS):
            return DownloadError(
                url,
                (
                    "yt-dlp could not solve YouTube's JavaScript challenge for "
                    "this video. Refresh yt-dlp/EJS support on the server and retry."
                ),
                code="YOUTUBE_CHALLENGE_FAILED",
                status_code=502,
                kind="challenge_failed",
                raw_reason=raw_reason,
            )

        if any(marker in combined for marker in self._STREAM_FORBIDDEN_MARKERS):
            return DownloadError(
                url,
                (
                    "YouTube rejected the media stream with HTTP 403. This usually "
                    "means stale auth, anti-bot rejection, or a client/runtime "
                    "mismatch."
                ),
                code="YOUTUBE_STREAM_FORBIDDEN",
                status_code=502,
                kind="stream_forbidden",
                raw_reason=raw_reason,
            )

        if any(marker in combined for marker in self._EMPTY_FILE_MARKERS):
            return DownloadError(
                url,
                (
                    "yt-dlp finished with an empty media file. This usually means "
                    "YouTube rejected the download mid-stream."
                ),
                code="YOUTUBE_EMPTY_DOWNLOAD",
                status_code=502,
                kind="empty_download",
                raw_reason=raw_reason,
            )

        return DownloadError(
            url,
            raw_reason,
            raw_reason=raw_reason,
        )
