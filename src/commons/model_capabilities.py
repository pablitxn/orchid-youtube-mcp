"""Model capabilities registry for multimodal content support."""

from dataclasses import dataclass
from enum import Enum


class ContentType(str, Enum):
    """Supported content types for multimodal messages."""

    TEXT = "text"
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


@dataclass(frozen=True)
class ModelCapabilities:
    """Capabilities of a specific LLM model."""

    text: bool = True
    image: bool = False
    audio: bool = False
    video: bool = False
    max_images: int = 0
    max_audio_seconds: int = 0
    max_video_seconds: int = 0
    context_window: int = 128_000

    def supports(self, content_type: ContentType) -> bool:
        """Check if model supports a content type."""
        mapping = {
            ContentType.TEXT: self.text,
            ContentType.IMAGE: self.image,
            ContentType.AUDIO: self.audio,
            ContentType.VIDEO: self.video,
        }
        return mapping.get(content_type, False)


# Registry of model capabilities
MODEL_CAPABILITIES: dict[str, ModelCapabilities] = {
    # Anthropic Claude models
    "claude-sonnet-4-20250514": ModelCapabilities(
        text=True,
        image=True,
        audio=False,
        video=False,
        max_images=20,
        context_window=200_000,
    ),
    "claude-opus-4-20250514": ModelCapabilities(
        text=True,
        image=True,
        audio=False,
        video=False,
        max_images=20,
        context_window=200_000,
    ),
    "claude-3-7-sonnet-20250219": ModelCapabilities(
        text=True,
        image=True,
        audio=False,
        video=False,
        max_images=20,
        context_window=200_000,
    ),
    "claude-3-5-sonnet-20241022": ModelCapabilities(
        text=True,
        image=True,
        audio=False,
        video=False,
        max_images=20,
        context_window=200_000,
    ),
    "claude-3-5-haiku-20241022": ModelCapabilities(
        text=True,
        image=True,
        audio=False,
        video=False,
        max_images=20,
        context_window=200_000,
    ),
    "claude-3-opus-20240229": ModelCapabilities(
        text=True,
        image=True,
        audio=False,
        video=False,
        max_images=20,
        context_window=200_000,
    ),
    # OpenAI models
    "gpt-4o": ModelCapabilities(
        text=True,
        image=True,
        audio=True,  # Audio preview support
        video=False,
        max_images=10,
        max_audio_seconds=300,
        context_window=128_000,
    ),
    "gpt-4o-mini": ModelCapabilities(
        text=True,
        image=True,
        audio=False,
        video=False,
        max_images=10,
        context_window=128_000,
    ),
    "gpt-4-turbo": ModelCapabilities(
        text=True,
        image=True,
        audio=False,
        video=False,
        max_images=10,
        context_window=128_000,
    ),
    # Google Gemini models
    "gemini-2.0-flash": ModelCapabilities(
        text=True,
        image=True,
        audio=True,
        video=True,  # Native video support
        max_images=16,
        max_audio_seconds=600,
        max_video_seconds=600,
        context_window=1_000_000,
    ),
    "gemini-1.5-pro": ModelCapabilities(
        text=True,
        image=True,
        audio=True,
        video=True,
        max_images=16,
        max_audio_seconds=600,
        max_video_seconds=600,
        context_window=2_000_000,
    ),
    "gemini-1.5-flash": ModelCapabilities(
        text=True,
        image=True,
        audio=True,
        video=True,
        max_images=16,
        max_audio_seconds=600,
        max_video_seconds=600,
        context_window=1_000_000,
    ),
}

# Default capabilities for unknown models (text-only)
DEFAULT_CAPABILITIES = ModelCapabilities(
    text=True,
    image=False,
    audio=False,
    video=False,
    context_window=128_000,
)


def get_model_capabilities(model_id: str) -> ModelCapabilities:
    """Get capabilities for a model, with fallback to defaults.

    Args:
        model_id: The model identifier string.

    Returns:
        ModelCapabilities for the model.
    """
    # Try exact match first
    if model_id in MODEL_CAPABILITIES:
        return MODEL_CAPABILITIES[model_id]

    # Try prefix match for versioned models
    for known_model, caps in MODEL_CAPABILITIES.items():
        if model_id.startswith(known_model.rsplit("-", 1)[0]):
            return caps

    return DEFAULT_CAPABILITIES


def get_supported_modalities(model_id: str) -> set[ContentType]:
    """Get set of supported content types for a model.

    Args:
        model_id: The model identifier string.

    Returns:
        Set of ContentType values the model supports.
    """
    caps = get_model_capabilities(model_id)
    supported = {ContentType.TEXT}  # Text always supported

    if caps.image:
        supported.add(ContentType.IMAGE)
    if caps.audio:
        supported.add(ContentType.AUDIO)
    if caps.video:
        supported.add(ContentType.VIDEO)

    return supported
