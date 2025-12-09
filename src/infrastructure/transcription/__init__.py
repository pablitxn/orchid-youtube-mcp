"""Transcription services."""

from src.infrastructure.transcription.base import (
    TranscriptionResult,
    TranscriptionSegment,
    TranscriptionServiceBase,
    TranscriptionWord,
)
from src.infrastructure.transcription.openai_whisper import OpenAIWhisperTranscription

__all__ = [
    # Base classes
    "TranscriptionServiceBase",
    "TranscriptionResult",
    "TranscriptionSegment",
    "TranscriptionWord",
    # Implementations
    "OpenAIWhisperTranscription",
]
