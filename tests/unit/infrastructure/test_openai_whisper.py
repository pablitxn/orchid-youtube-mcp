"""Unit tests for OpenAI Whisper transcription chunking."""

from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from openai import APIStatusError

from src.infrastructure.transcription.base import (
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionWord,
)
from src.infrastructure.transcription.openai_whisper import OpenAIWhisperTranscription


@pytest.fixture
def transcriber() -> OpenAIWhisperTranscription:
    """Create a Whisper transcriber instance for unit tests."""
    return OpenAIWhisperTranscription(api_key="test-key")


def _result(
    *,
    start: float,
    end: float,
    text: str,
    language: str = "en",
) -> TranscriptionResult:
    """Build a simple transcription result for assertions."""
    return TranscriptionResult(
        segments=[
            TranscriptionSegment(
                text=text,
                start_time=start,
                end_time=end,
                words=[
                    TranscriptionWord(
                        word=text,
                        start_time=start,
                        end_time=end,
                        confidence=1.0,
                    )
                ],
                language=language,
                confidence=1.0,
            )
        ],
        full_text=text,
        language=language,
        duration_seconds=end,
    )


class TestOpenAIWhisperTranscription:
    """Tests for chunk-aware Whisper transcription."""

    @pytest.mark.asyncio
    async def test_transcribe_uses_chunking_for_large_files(
        self,
        transcriber: OpenAIWhisperTranscription,
        tmp_path: Path,
    ) -> None:
        """Large uploads should skip direct Whisper upload and chunk first."""
        audio_path = tmp_path / "audio.mp3"
        audio_path.write_bytes(b"x" * 64)

        transcriber._TARGET_CHUNK_BYTES = 32  # type: ignore[misc]
        transcriber._transcribe_chunked = AsyncMock(  # type: ignore[method-assign]
            return_value=_result(start=0, end=5, text="chunked")
        )
        transcriber._transcribe_single_file = AsyncMock(  # type: ignore[method-assign]
            return_value=_result(start=0, end=5, text="single")
        )

        result = await transcriber.transcribe(str(audio_path))

        assert result.full_text == "chunked"
        transcriber._transcribe_chunked.assert_awaited_once()  # type: ignore[attr-defined]
        transcriber._transcribe_single_file.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_transcribe_retries_with_chunking_on_413(
        self,
        transcriber: OpenAIWhisperTranscription,
        tmp_path: Path,
    ) -> None:
        """A 413 from Whisper should transparently retry with chunking."""
        audio_path = tmp_path / "audio.mp3"
        audio_path.write_bytes(b"x" * 16)

        request = httpx.Request("POST", "https://api.openai.com/v1/audio/transcriptions")
        response = httpx.Response(status_code=413, request=request)
        too_large = APIStatusError(
            "too large",
            response=response,
            body={"error": {"message": "too large"}},
        )

        transcriber._transcribe_single_file = AsyncMock(  # type: ignore[method-assign]
            side_effect=too_large
        )
        transcriber._transcribe_chunked = AsyncMock(  # type: ignore[method-assign]
            return_value=_result(start=0, end=5, text="retried")
        )

        result = await transcriber.transcribe(str(audio_path))

        assert result.full_text == "retried"
        transcriber._transcribe_chunked.assert_awaited_once()  # type: ignore[attr-defined]

    def test_merge_results_preserves_offsets(
        self,
        transcriber: OpenAIWhisperTranscription,
    ) -> None:
        """Merged chunk results should keep timeline offsets intact."""
        merged = transcriber._merge_results(
            [
                _result(start=0, end=5, text="hello"),
                _result(start=5, end=9, text="world"),
            ],
            fallback_language="en",
        )

        assert merged.full_text == "hello world"
        assert merged.duration_seconds == 9
        assert merged.segments[1].start_time == 5

    def test_estimate_chunk_seconds_has_floor(
        self,
        transcriber: OpenAIWhisperTranscription,
    ) -> None:
        """Chunk estimation should never go below the configured floor."""
        assert (
            transcriber._estimate_chunk_seconds(
                file_size=10_000_000_000,
                duration_seconds=10,
            )
            == transcriber._MIN_CHUNK_SECONDS
        )
