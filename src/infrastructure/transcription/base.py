"""Abstract base class for transcription services."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass


@dataclass
class TranscriptionWord:
    """A single transcribed word with timing information."""

    word: str
    start_time: float
    end_time: float
    confidence: float


@dataclass
class TranscriptionSegment:
    """A segment of transcribed text with word-level details."""

    text: str
    start_time: float
    end_time: float
    words: list[TranscriptionWord]
    language: str
    confidence: float


@dataclass
class TranscriptionResult:
    """Complete transcription result."""

    segments: list[TranscriptionSegment]
    full_text: str
    language: str
    duration_seconds: float


class TranscriptionServiceBase(ABC):
    """Abstract base class for transcription services.

    Implementations should handle:
    - OpenAI Whisper API
    - Deepgram
    - AssemblyAI
    - Azure Speech
    - Google Speech-to-Text
    """

    @abstractmethod
    async def transcribe(
        self,
        audio_path: str,
        language_hint: str | None = None,
        word_timestamps: bool = True,
    ) -> TranscriptionResult:
        """Transcribe audio file to text with word-level timestamps.

        Args:
            audio_path: Path to the audio file.
            language_hint: Optional ISO language code hint (e.g., 'en', 'es').
            word_timestamps: Whether to include word-level timing.

        Returns:
            Complete transcription with segments and timing info.
        """

    @abstractmethod
    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        language_hint: str | None = None,
    ) -> AsyncIterator[TranscriptionSegment]:
        """Transcribe streaming audio in real-time.

        Args:
            audio_stream: Async iterator yielding audio chunks.
            language_hint: Optional ISO language code hint.

        Yields:
            Transcription segments as they become available.
        """
        # Make this a generator
        yield

    @abstractmethod
    def supported_languages(self) -> list[str]:
        """Return list of supported ISO language codes.

        Returns:
            List of language codes (e.g., ['en', 'es', 'fr']).
        """

    @property
    @abstractmethod
    def supports_word_timestamps(self) -> bool:
        """Whether this provider supports word-level timestamps.

        Returns:
            True if word timestamps are supported.
        """

    @property
    @abstractmethod
    def supports_streaming(self) -> bool:
        """Whether this provider supports streaming transcription.

        Returns:
            True if streaming is supported.
        """

    @property
    @abstractmethod
    def max_audio_duration_seconds(self) -> int | None:
        """Maximum audio duration supported, or None for unlimited.

        Returns:
            Maximum duration in seconds, or None if unlimited.
        """
