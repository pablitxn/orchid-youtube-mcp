"""Frame description generation service using vision LLM."""

import asyncio
import base64
from pathlib import Path
from typing import Any

from src.commons.infrastructure.blob.base import BlobStorageBase
from src.commons.model_capabilities import ContentType, get_supported_modalities
from src.commons.settings.models import VisualQuerySettings
from src.commons.telemetry import get_logger
from src.domain.models.chunk import FrameChunk
from src.infrastructure.llm.base import LLMServiceBase, Message, MessageRole


class FrameDescriptionService:
    """Service for generating AI descriptions of video frames.

    Uses a vision-capable LLM to analyze frames and generate detailed
    descriptions that include visible text, UI elements, and visual content.
    This enables semantic search to find visual content that isn't in the transcript.
    """

    def __init__(
        self,
        llm_service: LLMServiceBase,
        blob_storage: BlobStorageBase | None = None,
        settings: VisualQuerySettings | None = None,
        frames_bucket: str = "rag-frames",
    ) -> None:
        """Initialize frame description service.

        Args:
            llm_service: Vision-capable LLM service.
            blob_storage: Optional blob storage for presigned URLs.
            settings: Visual query settings.
            frames_bucket: Bucket name for frames.
        """
        self._llm = llm_service
        self._blob = blob_storage
        self._settings = settings or VisualQuerySettings()
        self._frames_bucket = frames_bucket
        self._logger = get_logger(__name__)

        # Check if LLM supports vision
        supported = get_supported_modalities(llm_service.default_model)
        self._supports_vision = ContentType.IMAGE in supported

        if not self._supports_vision:
            self._logger.warning(
                "LLM does not support vision, frame descriptions will be skipped",
                extra={"model_id": llm_service.default_model},
            )

    @property
    def supports_vision(self) -> bool:
        """Check if the configured LLM supports vision."""
        return self._supports_vision

    async def describe_frame(
        self,
        frame: FrameChunk,
        image_path: Path | str | None = None,
        use_presigned_url: bool = True,
    ) -> str | None:
        """Generate a description for a single frame.

        Args:
            frame: The frame chunk to describe.
            image_path: Local path to image file (if available).
            use_presigned_url: Whether to use presigned URL from blob storage.

        Returns:
            AI-generated description or None if failed.
        """
        if not self._supports_vision:
            return None

        try:
            # Build message with image
            image_content = await self._get_image_content(
                frame, image_path, use_presigned_url
            )
            if not image_content:
                return None

            # Create messages for the LLM
            system_message = Message(
                role=MessageRole.SYSTEM,
                content=(
                    "You are a visual analysis assistant. Describe video frames "
                    "accurately and concisely. Focus on identifying and transcribing "
                    "any visible text, code, names, or numbers."
                ),
            )

            user_message = Message(
                role=MessageRole.USER,
                content=self._settings.frame_description_prompt,
                images=[image_content],
            )

            response = await self._llm.generate(
                messages=[system_message, user_message],
                temperature=0.3,
                max_tokens=500,
            )

            description = response.content.strip()

            self._logger.debug(
                "Generated frame description",
                extra={
                    "frame_id": frame.id,
                    "description_length": len(description),
                },
            )

            return description

        except Exception as e:
            self._logger.error(
                "Failed to generate frame description",
                extra={"frame_id": frame.id, "error": str(e)},
            )
            return None

    async def describe_frames_batch(
        self,
        frames: list[FrameChunk],
        local_paths: dict[str, Path] | None = None,
        concurrency: int = 3,
        progress_callback: Any | None = None,
    ) -> list[FrameChunk]:
        """Generate descriptions for multiple frames.

        Args:
            frames: List of frame chunks to describe.
            local_paths: Optional mapping of frame ID to local file path.
            concurrency: Maximum concurrent description requests.
            progress_callback: Optional callback(completed, total) for progress.

        Returns:
            List of frame chunks with descriptions added.
        """
        if not self._supports_vision:
            self._logger.info(
                "Skipping frame descriptions - LLM does not support vision",
                extra={"frame_count": len(frames)},
            )
            return frames

        if not self._settings.generate_frame_descriptions:
            self._logger.info(
                "Skipping frame descriptions - disabled in settings",
                extra={"frame_count": len(frames)},
            )
            return frames

        self._logger.info(
            "Starting batch frame description generation",
            extra={
                "frame_count": len(frames),
                "concurrency": concurrency,
            },
        )

        local_paths = local_paths or {}
        semaphore = asyncio.Semaphore(concurrency)
        completed = 0

        async def describe_with_limit(frame: FrameChunk) -> FrameChunk:
            nonlocal completed
            async with semaphore:
                local_path = local_paths.get(frame.id)
                description = await self.describe_frame(
                    frame,
                    image_path=local_path,
                    use_presigned_url=local_path is None,
                )

                completed += 1
                if progress_callback:
                    progress_callback(completed, len(frames))

                if description:
                    return frame.with_description(description)
                return frame

        # Process all frames with concurrency limit
        tasks = [describe_with_limit(frame) for frame in frames]
        described_frames = await asyncio.gather(*tasks)

        success_count = sum(1 for f in described_frames if f.description)
        self._logger.info(
            "Batch frame description completed",
            extra={
                "total_frames": len(frames),
                "successful_descriptions": success_count,
                "failed": len(frames) - success_count,
            },
        )

        return list(described_frames)

    async def _get_image_content(
        self,
        frame: FrameChunk,
        local_path: Path | str | None,
        use_presigned_url: bool,
    ) -> str | None:
        """Get image content as URL or base64 for LLM.

        Args:
            frame: Frame chunk.
            local_path: Optional local file path.
            use_presigned_url: Whether to try presigned URL first.

        Returns:
            Image URL or base64 data URL, or None if unavailable.
        """
        # Try presigned URL first if blob storage available
        if use_presigned_url and self._blob:
            try:
                url = await self._blob.generate_presigned_url(
                    bucket=self._frames_bucket,
                    path=frame.blob_path,
                    expiry_seconds=3600,
                )
                return url
            except Exception as e:
                self._logger.debug(
                    "Could not get presigned URL, trying local path",
                    extra={"error": str(e)},
                )

        # Try local file
        if local_path:
            path = Path(local_path)
            if path.exists():
                try:
                    content = path.read_bytes()
                    b64 = base64.b64encode(content).decode("utf-8")
                    # Determine mime type
                    suffix = path.suffix.lower()
                    mime_types = {
                        ".jpg": "image/jpeg",
                        ".jpeg": "image/jpeg",
                        ".png": "image/png",
                        ".webp": "image/webp",
                        ".gif": "image/gif",
                    }
                    mime = mime_types.get(suffix, "image/jpeg")
                    return f"data:{mime};base64,{b64}"
                except Exception as e:
                    self._logger.debug(
                        "Could not read local file",
                        extra={"path": str(path), "error": str(e)},
                    )

        return None
