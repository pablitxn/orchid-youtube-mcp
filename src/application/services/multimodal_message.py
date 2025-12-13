"""Multimodal message builder for LLM requests."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Self

from src.commons.model_capabilities import (
    ContentType,
    get_model_capabilities,
    get_supported_modalities,
)
from src.domain.models.chunk import (
    AudioChunk,
    BaseChunk,
    FrameChunk,
    TranscriptChunk,
    VideoChunk,
)
from src.infrastructure.llm.base import Message, MessageRole

if TYPE_CHECKING:
    from src.commons.infrastructure.blob.base import BlobStorageBase


@dataclass
class ContentBlock:
    """A single content block in a multimodal message."""

    type: ContentType
    content: str  # Text content, URL, or base64
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_text(self) -> bool:
        """Check if this is a text block."""
        return self.type == ContentType.TEXT

    def is_media(self) -> bool:
        """Check if this is a media block (image/audio/video)."""
        return self.type in {ContentType.IMAGE, ContentType.AUDIO, ContentType.VIDEO}


@dataclass
class MultimodalMessage:
    """A message composed of multiple content blocks."""

    role: MessageRole
    blocks: list[ContentBlock] = field(default_factory=list)

    def to_llm_message(self) -> Message:
        """Convert to LLM Message format.

        Combines all text blocks and extracts media URLs.
        """
        text_parts: list[str] = []
        images: list[str] = []
        videos: list[str] = []

        for block in self.blocks:
            if block.type == ContentType.TEXT:
                text_parts.append(block.content)
            elif block.type == ContentType.IMAGE:
                images.append(block.content)
            elif block.type == ContentType.VIDEO:
                videos.append(block.content)
            # Audio is handled specially by provider-specific code

        return Message(
            role=self.role,
            content="\n\n".join(text_parts),
            images=images if images else None,
            videos=videos if videos else None,
        )

    def get_text_content(self) -> str:
        """Get combined text content from all text blocks."""
        return "\n\n".join(
            block.content for block in self.blocks if block.type == ContentType.TEXT
        )

    def get_image_urls(self) -> list[str]:
        """Get all image URLs/base64 strings."""
        return [
            block.content for block in self.blocks if block.type == ContentType.IMAGE
        ]

    def get_audio_urls(self) -> list[str]:
        """Get all audio URLs."""
        return [
            block.content for block in self.blocks if block.type == ContentType.AUDIO
        ]

    def get_video_urls(self) -> list[str]:
        """Get all video URLs."""
        return [
            block.content for block in self.blocks if block.type == ContentType.VIDEO
        ]

    @property
    def image_count(self) -> int:
        """Count of image blocks."""
        return sum(1 for b in self.blocks if b.type == ContentType.IMAGE)

    @property
    def has_media(self) -> bool:
        """Check if message contains any media."""
        return any(b.is_media() for b in self.blocks)


class MultimodalMessageBuilder:
    """Builder for constructing multimodal messages.

    Validates content against model capabilities and enabled modalities.

    Example:
        builder = MultimodalMessageBuilder("claude-sonnet-4-20250514")
        builder.enable_modality(ContentType.IMAGE)

        message = (
            builder
            .add_text("Analyze this video segment:")
            .add_chunk_context(transcript_chunk)
            .add_chunk_context(frame_chunk)  # Image added if enabled
            .add_text("What is being discussed?")
            .build()
        )
    """

    def __init__(
        self,
        model_id: str,
        enabled_modalities: set[ContentType] | None = None,
        blob_storage: "BlobStorageBase | None" = None,
    ) -> None:
        """Initialize the builder.

        Args:
            model_id: The LLM model identifier.
            enabled_modalities: Set of modalities to include. Defaults to TEXT only.
            blob_storage: Optional blob storage for generating presigned URLs.
        """
        self.model_id = model_id
        self.capabilities = get_model_capabilities(model_id)
        self.supported = get_supported_modalities(model_id)
        self.blob_storage = blob_storage

        # Default: only text enabled
        self._enabled = enabled_modalities or {ContentType.TEXT}

        # Validate enabled modalities are supported
        unsupported = self._enabled - self.supported
        if unsupported:
            # Silently filter to supported only (no error, just skip)
            self._enabled = self._enabled & self.supported

        self._blocks: list[ContentBlock] = []
        self._role = MessageRole.USER

    def set_role(self, role: MessageRole) -> Self:
        """Set the message role."""
        self._role = role
        return self

    def enable_modality(self, modality: ContentType) -> Self:
        """Enable a modality if the model supports it.

        Args:
            modality: The content type to enable.

        Returns:
            Self for chaining.
        """
        if modality in self.supported:
            self._enabled.add(modality)
        return self

    def disable_modality(self, modality: ContentType) -> Self:
        """Disable a modality.

        Args:
            modality: The content type to disable.

        Returns:
            Self for chaining.
        """
        self._enabled.discard(modality)
        # Always keep text enabled
        self._enabled.add(ContentType.TEXT)
        return self

    def enable_all_supported(self) -> Self:
        """Enable all modalities the model supports."""
        self._enabled = self.supported.copy()
        return self

    def is_enabled(self, modality: ContentType) -> bool:
        """Check if a modality is enabled."""
        return modality in self._enabled

    def add_text(
        self,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> Self:
        """Add a text block.

        Args:
            text: The text content.
            metadata: Optional metadata (e.g., timestamp info).

        Returns:
            Self for chaining.
        """
        if not text.strip():
            return self

        self._blocks.append(
            ContentBlock(
                type=ContentType.TEXT,
                content=text,
                metadata=metadata or {},
            )
        )
        return self

    def add_image(
        self,
        image: str,
        metadata: dict[str, Any] | None = None,
    ) -> Self:
        """Add an image block if images are enabled.

        Args:
            image: Image URL or base64 string.
            metadata: Optional metadata.

        Returns:
            Self for chaining.
        """
        if ContentType.IMAGE not in self._enabled:
            return self

        # Check max images limit
        if self._count_type(ContentType.IMAGE) >= self.capabilities.max_images:
            return self

        self._blocks.append(
            ContentBlock(
                type=ContentType.IMAGE,
                content=image,
                metadata=metadata or {},
            )
        )
        return self

    def add_audio(
        self,
        audio_url: str,
        metadata: dict[str, Any] | None = None,
    ) -> Self:
        """Add an audio block if audio is enabled.

        Args:
            audio_url: URL to audio file.
            metadata: Optional metadata.

        Returns:
            Self for chaining.
        """
        if ContentType.AUDIO not in self._enabled:
            return self

        self._blocks.append(
            ContentBlock(
                type=ContentType.AUDIO,
                content=audio_url,
                metadata=metadata or {},
            )
        )
        return self

    def add_video(
        self,
        video_url: str,
        metadata: dict[str, Any] | None = None,
    ) -> Self:
        """Add a video block if video is enabled.

        Args:
            video_url: URL to video file.
            metadata: Optional metadata.

        Returns:
            Self for chaining.
        """
        if ContentType.VIDEO not in self._enabled:
            return self

        self._blocks.append(
            ContentBlock(
                type=ContentType.VIDEO,
                content=video_url,
                metadata=metadata or {},
            )
        )
        return self

    async def add_chunk_context(
        self,
        chunk: BaseChunk,
        bucket: str = "rag-chunks",
        include_timestamp_header: bool = True,
    ) -> Self:
        """Add context from a chunk based on its type.

        Automatically adds the appropriate content type based on the chunk:
        - TranscriptChunk → text
        - FrameChunk → image (if enabled)
        - AudioChunk → audio (if enabled)
        - VideoChunk → video (if enabled)

        Args:
            chunk: The chunk to add context from.
            bucket: Blob storage bucket for media files.
            include_timestamp_header: Whether to include timestamp info.

        Returns:
            Self for chaining.
        """
        timestamp_info = ""
        if include_timestamp_header:
            timestamp_info = f"[{chunk.format_time_range()}]"

        if isinstance(chunk, TranscriptChunk):
            text = f"{timestamp_info} {chunk.text}" if timestamp_info else chunk.text
            self.add_text(
                text,
                metadata={
                    "chunk_id": chunk.id,
                    "start_time": chunk.start_time,
                    "end_time": chunk.end_time,
                    "modality": "transcript",
                },
            )

        elif isinstance(chunk, FrameChunk):
            # Always add description as text if available
            if chunk.description:
                desc = f"{timestamp_info} [Frame] {chunk.description}"
                self.add_text(
                    desc,
                    metadata={"chunk_id": chunk.id, "modality": "frame_description"},
                )

            # Add image if enabled and we have blob storage
            if ContentType.IMAGE in self._enabled and self.blob_storage:
                url = await self.blob_storage.generate_presigned_url(
                    bucket="rag-frames",
                    path=chunk.blob_path,
                    expiry_seconds=3600,
                )
                self.add_image(
                    url,
                    metadata={
                        "chunk_id": chunk.id,
                        "frame_number": chunk.frame_number,
                        "timestamp": chunk.start_time,
                    },
                )

        elif isinstance(chunk, AudioChunk):
            # Add audio if enabled and we have blob storage
            if ContentType.AUDIO in self._enabled and self.blob_storage:
                url = await self.blob_storage.generate_presigned_url(
                    bucket=bucket,
                    path=chunk.blob_path,
                    expiry_seconds=3600,
                )
                self.add_audio(
                    url,
                    metadata={
                        "chunk_id": chunk.id,
                        "start_time": chunk.start_time,
                        "end_time": chunk.end_time,
                    },
                )

        elif isinstance(chunk, VideoChunk):
            # Add description as text if available
            if chunk.description:
                desc = f"{timestamp_info} [Video] {chunk.description}"
                self.add_text(
                    desc,
                    metadata={"chunk_id": chunk.id, "modality": "video_description"},
                )

            # Add video if enabled and we have blob storage
            if ContentType.VIDEO in self._enabled and self.blob_storage:
                url = await self.blob_storage.generate_presigned_url(
                    bucket=bucket,
                    path=chunk.blob_path,
                    expiry_seconds=3600,
                )
                self.add_video(
                    url,
                    metadata={
                        "chunk_id": chunk.id,
                        "start_time": chunk.start_time,
                        "end_time": chunk.end_time,
                        "duration": chunk.duration_seconds,
                    },
                )

        return self

    def add_separator(self, separator: str = "---") -> Self:
        """Add a text separator between content blocks."""
        return self.add_text(separator)

    def build(self) -> MultimodalMessage:
        """Build the final multimodal message.

        Returns:
            The constructed MultimodalMessage.
        """
        return MultimodalMessage(
            role=self._role,
            blocks=self._blocks.copy(),
        )

    def build_as_llm_message(self) -> Message:
        """Build and convert directly to LLM Message format.

        Returns:
            A Message ready for LLM consumption.
        """
        return self.build().to_llm_message()

    def clear(self) -> Self:
        """Clear all blocks and reset builder."""
        self._blocks = []
        return self

    def _count_type(self, content_type: ContentType) -> int:
        """Count blocks of a specific type."""
        return sum(1 for b in self._blocks if b.type == content_type)

    @property
    def block_count(self) -> int:
        """Total number of content blocks."""
        return len(self._blocks)

    @property
    def enabled_modalities(self) -> set[ContentType]:
        """Get currently enabled modalities."""
        return self._enabled.copy()

    def __repr__(self) -> str:
        """String representation."""
        modalities = ", ".join(m.value for m in self._enabled)
        return (
            f"MultimodalMessageBuilder(model={self.model_id}, "
            f"enabled=[{modalities}], blocks={self.block_count})"
        )


def create_context_message(
    chunks: list[BaseChunk],
    query: str,
    model_id: str,
    enabled_modalities: set[ContentType] | None = None,
    blob_storage: "BlobStorageBase | None" = None,
    system_prompt: str | None = None,
) -> list[Message]:
    """Convenience function to create messages from chunks.

    Creates a properly formatted message list for LLM consumption.

    Args:
        chunks: List of chunks to include as context.
        query: The user's query.
        model_id: Target LLM model.
        enabled_modalities: Which modalities to include.
        blob_storage: Blob storage for presigned URLs.
        system_prompt: Optional system prompt.

    Returns:
        List of Messages ready for LLM.
    """
    messages: list[Message] = []

    if system_prompt:
        messages.append(Message(role=MessageRole.SYSTEM, content=system_prompt))

    # Build context message
    builder = MultimodalMessageBuilder(
        model_id=model_id,
        enabled_modalities=enabled_modalities,
        blob_storage=blob_storage,
    )

    builder.add_text("Here is the relevant context from the video:\n")

    # Note: add_chunk_context is async, so this sync helper only adds text
    # For full multimodal support, use the builder directly with await
    for chunk in chunks:
        if isinstance(chunk, TranscriptChunk):
            timestamp_info = f"[{chunk.format_time_range()}]"
            builder.add_text(
                f"{timestamp_info} {chunk.text}",
                metadata={"chunk_id": chunk.id},
            )
        elif isinstance(chunk, FrameChunk) and chunk.description:
            timestamp_info = f"[{chunk.format_time_range()}]"
            builder.add_text(
                f"{timestamp_info} [Frame] {chunk.description}",
                metadata={"chunk_id": chunk.id},
            )
        elif isinstance(chunk, VideoChunk) and chunk.description:
            timestamp_info = f"[{chunk.format_time_range()}]"
            builder.add_text(
                f"{timestamp_info} [Video] {chunk.description}",
                metadata={"chunk_id": chunk.id},
            )

    builder.add_text(f"\n\nQuestion: {query}")

    messages.append(builder.build_as_llm_message())

    return messages
