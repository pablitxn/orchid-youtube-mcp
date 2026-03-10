"""OpenAI Whisper implementation of transcription service."""

import asyncio
import json
import subprocess
import tempfile
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar, cast

from openai import APIStatusError, AsyncOpenAI

from src.infrastructure.telemetry import get_logger
from src.infrastructure.transcription.base import (
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionServiceBase,
    TranscriptionWord,
)


@dataclass(frozen=True)
class _AudioChunk:
    """Temporary audio chunk prepared for Whisper upload."""

    path: Path
    start_time: float
    end_time: float
    size_bytes: int


class OpenAIWhisperTranscription(TranscriptionServiceBase):
    """OpenAI Whisper API implementation of transcription service.

    Uses the OpenAI Whisper API for high-quality transcription with
    word-level timestamps.
    """

    # Whisper supported languages (ISO 639-1 codes)
    _SUPPORTED_LANGUAGES: ClassVar[list[str]] = [
        "af",
        "ar",
        "hy",
        "az",
        "be",
        "bs",
        "bg",
        "ca",
        "zh",
        "hr",
        "cs",
        "da",
        "nl",
        "en",
        "et",
        "fi",
        "fr",
        "gl",
        "de",
        "el",
        "he",
        "hi",
        "hu",
        "is",
        "id",
        "it",
        "ja",
        "kn",
        "kk",
        "ko",
        "lv",
        "lt",
        "mk",
        "ms",
        "mr",
        "mi",
        "ne",
        "no",
        "fa",
        "pl",
        "pt",
        "ro",
        "ru",
        "sr",
        "sk",
        "sl",
        "es",
        "sw",
        "sv",
        "tl",
        "ta",
        "th",
        "tr",
        "uk",
        "ur",
        "vi",
        "cy",
    ]
    _MAX_UPLOAD_BYTES: ClassVar[int] = 25 * 1024 * 1024
    _TARGET_CHUNK_BYTES: ClassVar[int] = 23 * 1024 * 1024
    _MIN_CHUNK_SECONDS: ClassVar[int] = 30
    _CHUNK_AUDIO_BITRATE: ClassVar[str] = "96k"
    _CHUNK_AUDIO_SAMPLE_RATE: ClassVar[int] = 16000
    _CHUNK_AUDIO_CHANNELS: ClassVar[int] = 1

    def __init__(
        self,
        api_key: str,
        model: str = "whisper-1",
        base_url: str | None = None,
    ) -> None:
        """Initialize OpenAI Whisper client.

        Args:
            api_key: OpenAI API key.
            model: Whisper model to use.
            base_url: Optional custom API endpoint (for Azure, etc.).
        """
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self._model = model
        self._logger = get_logger(__name__)

    async def transcribe(
        self,
        audio_path: str,
        language_hint: str | None = None,
        word_timestamps: bool = True,
    ) -> TranscriptionResult:
        """Transcribe audio file to text with word-level timestamps."""
        path = Path(audio_path)
        if path.stat().st_size > self._TARGET_CHUNK_BYTES:
            return await self._transcribe_chunked(
                path,
                language_hint=language_hint,
                word_timestamps=word_timestamps,
            )

        try:
            return await self._transcribe_single_file(
                path,
                language_hint=language_hint,
                word_timestamps=word_timestamps,
            )
        except APIStatusError as exc:
            if exc.status_code == 413:
                self._logger.warning(
                    "Whisper upload exceeded size limit, retrying with audio chunking",
                    extra={
                        "audio_path": str(path),
                        "size_bytes": path.stat().st_size,
                    },
                )
                return await self._transcribe_chunked(
                    path,
                    language_hint=language_hint,
                    word_timestamps=word_timestamps,
                )
            raise

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language_hint: str | None = None,
    ) -> AsyncIterator[TranscriptionSegment]:
        """Transcribe streaming audio in real-time.

        Note: OpenAI Whisper API doesn't support streaming transcription.
        This method collects the full audio and processes it.
        """
        # Collect all audio chunks
        chunks: list[bytes] = []
        async for chunk in audio_stream:
            chunks.append(chunk)

        # Write to temporary file and transcribe
        import tempfile

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            tmp.write(b"".join(chunks))
            tmp_path = tmp.name

        try:
            result = await self.transcribe(tmp_path, language_hint)
            for segment in result.segments:
                yield segment
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def supported_languages(self) -> list[str]:
        """Return list of supported ISO language codes."""
        return self._SUPPORTED_LANGUAGES.copy()

    @property
    def supports_word_timestamps(self) -> bool:
        """Whether this provider supports word-level timestamps."""
        return True

    @property
    def supports_streaming(self) -> bool:
        """Whether this provider supports streaming transcription."""
        return False  # OpenAI Whisper API doesn't support true streaming

    @property
    def max_audio_duration_seconds(self) -> int | None:
        """Maximum audio duration supported."""
        # Whisper API has a file size limit of 25MB, not duration
        # But we return None for unlimited duration (will need chunking for long files)
        return None

    async def _transcribe_single_file(
        self,
        path: Path,
        *,
        language_hint: str | None,
        word_timestamps: bool,
        time_offset: float = 0.0,
    ) -> TranscriptionResult:
        """Transcribe a single audio file upload with optional time offset."""
        with path.open("rb") as audio_file:
            create_fn = cast("Any", self._client.audio.transcriptions.create)
            response = await create_fn(
                model=self._model,
                file=audio_file,
                language=language_hint,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"]
                if word_timestamps
                else ["segment"],
            )

        return self._response_to_result(
            response,
            language_hint=language_hint,
            word_timestamps=word_timestamps,
            time_offset=time_offset,
        )

    def _response_to_result(
        self,
        response: Any,
        *,
        language_hint: str | None,
        word_timestamps: bool,
        time_offset: float = 0.0,
    ) -> TranscriptionResult:
        """Convert a Whisper verbose_json response into the shared result model."""
        segments: list[TranscriptionSegment] = []
        response_segments = getattr(response, "segments", None) or []
        response_words = getattr(response, "words", None) or []
        word_idx = 0
        resolved_language = getattr(response, "language", language_hint or "en")

        for seg in response_segments:
            seg_start = float(getattr(seg, "start", 0)) + time_offset
            seg_end = float(getattr(seg, "end", 0)) + time_offset
            seg_text = getattr(seg, "text", "")
            segment_words: list[TranscriptionWord] = []

            if word_timestamps and response_words:
                while word_idx < len(response_words):
                    word_data = response_words[word_idx]
                    word_start = float(getattr(word_data, "start", 0)) + time_offset
                    word_end = float(getattr(word_data, "end", 0)) + time_offset

                    if word_start >= seg_start and word_end <= seg_end + 0.1:
                        segment_words.append(
                            TranscriptionWord(
                                word=getattr(word_data, "word", "").strip(),
                                start_time=word_start,
                                end_time=word_end,
                                confidence=1.0,
                            )
                        )
                        word_idx += 1
                    elif word_start > seg_end:
                        break
                    else:
                        word_idx += 1

            segments.append(
                TranscriptionSegment(
                    text=seg_text.strip(),
                    start_time=seg_start,
                    end_time=seg_end,
                    words=segment_words,
                    language=resolved_language,
                    confidence=1.0,
                )
            )

        duration = segments[-1].end_time if segments else time_offset
        return TranscriptionResult(
            segments=segments,
            full_text=getattr(response, "text", "").strip(),
            language=resolved_language,
            duration_seconds=duration,
        )

    async def _transcribe_chunked(
        self,
        path: Path,
        *,
        language_hint: str | None,
        word_timestamps: bool,
    ) -> TranscriptionResult:
        """Split oversized audio and merge the per-chunk Whisper responses."""
        file_size = path.stat().st_size
        duration_seconds = await self._get_audio_duration(path)
        chunk_seconds = self._estimate_chunk_seconds(
            file_size=file_size,
            duration_seconds=duration_seconds,
        )

        self._logger.info(
            "Transcribing oversized audio via chunked uploads",
            extra={
                "audio_path": str(path),
                "size_bytes": file_size,
                "duration_seconds": round(duration_seconds, 2),
                "initial_chunk_seconds": chunk_seconds,
            },
        )

        with tempfile.TemporaryDirectory(prefix="whisper-chunks-") as temp_dir:
            chunk_dir = Path(temp_dir)
            chunks = await self._split_audio_until_uploadable(
                path,
                chunk_dir,
                chunk_seconds=chunk_seconds,
            )

            results: list[TranscriptionResult] = []
            for chunk in chunks:
                result = await self._transcribe_single_file(
                    chunk.path,
                    language_hint=language_hint,
                    word_timestamps=word_timestamps,
                    time_offset=chunk.start_time,
                )
                results.append(result)

        return self._merge_results(results, fallback_language=language_hint or "en")

    async def _split_audio_until_uploadable(
        self,
        path: Path,
        output_dir: Path,
        *,
        chunk_seconds: int,
    ) -> list[_AudioChunk]:
        """Split audio and retry with smaller windows until every chunk fits."""
        current_chunk_seconds = chunk_seconds

        while True:
            chunks = await self._split_audio_file(
                path,
                output_dir,
                chunk_seconds=current_chunk_seconds,
            )
            if not chunks:
                return []

            max_chunk_size = max(chunk.size_bytes for chunk in chunks)
            if (
                max_chunk_size <= self._TARGET_CHUNK_BYTES
                or current_chunk_seconds <= self._MIN_CHUNK_SECONDS
            ):
                return chunks

            current_chunk_seconds = max(
                self._MIN_CHUNK_SECONDS,
                current_chunk_seconds // 2,
            )
            self._logger.warning(
                "Audio chunks still exceed Whisper upload target; "
                "retrying smaller windows",
                extra={
                    "audio_path": str(path),
                    "max_chunk_size": max_chunk_size,
                    "next_chunk_seconds": current_chunk_seconds,
                },
            )

    async def _split_audio_file(
        self,
        path: Path,
        output_dir: Path,
        *,
        chunk_seconds: int,
    ) -> list[_AudioChunk]:
        """Create sequential transcription chunks from the source audio."""
        duration = await self._get_audio_duration(path)
        output_dir.mkdir(parents=True, exist_ok=True)
        for existing in output_dir.glob("chunk_*.mp3"):
            existing.unlink()

        chunks: list[_AudioChunk] = []
        current_time = 0.0
        chunk_idx = 0

        while current_time < duration:
            chunk_idx += 1
            start_time = current_time
            end_time = min(start_time + chunk_seconds, duration)
            output_path = output_dir / f"chunk_{chunk_idx:04d}.mp3"
            await self._extract_audio_chunk(
                source_path=path,
                output_path=output_path,
                start_time=start_time,
                end_time=end_time,
            )
            chunks.append(
                _AudioChunk(
                    path=output_path,
                    start_time=start_time,
                    end_time=end_time,
                    size_bytes=output_path.stat().st_size,
                )
            )
            current_time = end_time

        return chunks

    async def _extract_audio_chunk(
        self,
        *,
        source_path: Path,
        output_path: Path,
        start_time: float,
        end_time: float,
    ) -> None:
        """Extract a speech-friendly mp3 segment with ffmpeg."""
        duration = max(0.0, end_time - start_time)
        cmd = [
            "ffmpeg",
            "-loglevel",
            "error",
            "-ss",
            str(start_time),
            "-i",
            str(source_path),
            "-t",
            str(duration),
            "-vn",
            "-ac",
            str(self._CHUNK_AUDIO_CHANNELS),
            "-ar",
            str(self._CHUNK_AUDIO_SAMPLE_RATE),
            "-acodec",
            "libmp3lame",
            "-b:a",
            self._CHUNK_AUDIO_BITRATE,
            "-y",
            str(output_path),
        ]

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None,
            lambda: subprocess.run(cmd, capture_output=True, check=True),
        )

    async def _get_audio_duration(self, path: Path) -> float:
        """Read audio duration from ffprobe."""
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            str(path),
        ]
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                cmd,
                capture_output=True,
                check=True,
                text=True,
            ),
        )
        payload = json.loads(result.stdout)
        return float(payload.get("format", {}).get("duration", 0.0))

    def _estimate_chunk_seconds(
        self,
        *,
        file_size: int,
        duration_seconds: float,
    ) -> int:
        """Estimate a safe chunk duration based on file size and duration."""
        if file_size <= 0 or duration_seconds <= 0:
            return self._MIN_CHUNK_SECONDS

        ratio = self._TARGET_CHUNK_BYTES / file_size
        estimated = int(duration_seconds * ratio)
        return max(self._MIN_CHUNK_SECONDS, estimated)

    def _merge_results(
        self,
        results: list[TranscriptionResult],
        *,
        fallback_language: str,
    ) -> TranscriptionResult:
        """Merge chunked transcription results into one timeline."""
        merged_segments: list[TranscriptionSegment] = []
        full_text_parts: list[str] = []

        for result in results:
            merged_segments.extend(result.segments)
            if result.full_text.strip():
                full_text_parts.append(result.full_text.strip())

        language = (
            next((result.language for result in results if result.language), None)
            or fallback_language
        )
        duration = merged_segments[-1].end_time if merged_segments else 0.0

        return TranscriptionResult(
            segments=merged_segments,
            full_text=" ".join(full_text_parts).strip(),
            language=language,
            duration_seconds=duration,
        )
