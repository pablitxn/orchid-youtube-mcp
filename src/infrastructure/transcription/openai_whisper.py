"""OpenAI Whisper implementation of transcription service."""

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar, cast

from openai import AsyncOpenAI

from src.infrastructure.transcription.base import (
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionServiceBase,
    TranscriptionWord,
)


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

    async def transcribe(
        self,
        audio_path: str,
        language_hint: str | None = None,
        word_timestamps: bool = True,
    ) -> TranscriptionResult:
        """Transcribe audio file to text with word-level timestamps."""
        path = Path(audio_path)

        with path.open("rb") as audio_file:
            # Use verbose_json to get word-level timestamps
            # Cast to Any to work around strict overload typing in OpenAI SDK
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

        segments: list[TranscriptionSegment] = []

        # Process segments from response
        response_segments = getattr(response, "segments", None) or []
        response_words = getattr(response, "words", None) or []

        # Build word index for quick lookup
        word_idx = 0

        for seg in response_segments:
            seg_start = float(seg.get("start", 0))
            seg_end = float(seg.get("end", 0))
            seg_text = seg.get("text", "")

            # Collect words for this segment
            segment_words: list[TranscriptionWord] = []

            if word_timestamps and response_words:
                while word_idx < len(response_words):
                    word_data = response_words[word_idx]
                    word_start = float(word_data.get("start", 0))
                    word_end = float(word_data.get("end", 0))

                    # Check if word belongs to this segment
                    if word_start >= seg_start and word_end <= seg_end + 0.1:
                        segment_words.append(
                            TranscriptionWord(
                                word=word_data.get("word", "").strip(),
                                start_time=word_start,
                                end_time=word_end,
                                confidence=1.0,  # Whisper: no word conf
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
                    language=getattr(response, "language", language_hint or "en"),
                    confidence=1.0,  # Whisper doesn't provide segment confidence
                )
            )

        # Calculate duration from last segment
        duration = segments[-1].end_time if segments else 0.0

        return TranscriptionResult(
            segments=segments,
            full_text=getattr(response, "text", ""),
            language=getattr(response, "language", language_hint or "en"),
            duration_seconds=duration,
        )

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
