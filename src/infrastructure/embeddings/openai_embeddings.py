"""OpenAI implementation of text embedding service."""

from typing import ClassVar

from openai import AsyncOpenAI

from src.infrastructure.embeddings.base import (
    EmbeddingModality,
    EmbeddingResult,
    EmbeddingServiceBase,
)


class OpenAIEmbeddingService(EmbeddingServiceBase):
    """OpenAI implementation of text embedding service.

    Uses OpenAI's text-embedding models (e.g., text-embedding-3-small/large).
    """

    # Model dimensions
    _MODEL_DIMENSIONS: ClassVar[dict[str, int]] = {
        "text-embedding-3-small": 1536,
        "text-embedding-3-large": 3072,
        "text-embedding-ada-002": 1536,
    }

    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        base_url: str | None = None,
    ) -> None:
        """Initialize OpenAI embedding client.

        Args:
            api_key: OpenAI API key.
            model: Embedding model to use.
            base_url: Optional custom API endpoint (for Azure, etc.).
        """
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        self._model = model
        self._dimensions = self._MODEL_DIMENSIONS.get(model, 1536)

    async def embed_text(
        self,
        text: str,
        model: str | None = None,
    ) -> EmbeddingResult:
        """Generate embedding for a single text."""
        use_model = model or self._model

        response = await self._client.embeddings.create(
            model=use_model,
            input=text,
        )

        embedding = response.data[0].embedding
        tokens_used = response.usage.total_tokens if response.usage else None

        return EmbeddingResult(
            vector=embedding,
            dimensions=len(embedding),
            model=use_model,
            modality=EmbeddingModality.TEXT,
            tokens_used=tokens_used,
        )

    async def embed_texts(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[EmbeddingResult]:
        """Generate embeddings for multiple texts (batched)."""
        if not texts:
            return []

        # Validate and sanitize inputs - OpenAI API rejects empty strings
        sanitized_texts: list[str] = []
        for i, text in enumerate(texts):
            if text is None:
                raise ValueError(f"Text at index {i} is None, expected string")
            if not isinstance(text, str):
                raise ValueError(
                    f"Text at index {i} has type {type(text).__name__}, expected str"
                )
            # Replace empty strings with a single space (minimum valid input)
            sanitized_texts.append(text if text.strip() else " ")

        use_model = model or self._model

        # Process in batches of max_batch_size
        results: list[EmbeddingResult] = []
        for i in range(0, len(sanitized_texts), self.max_batch_size):
            batch = sanitized_texts[i : i + self.max_batch_size]

            response = await self._client.embeddings.create(
                model=use_model,
                input=batch,
            )

            tokens_per_item = None
            if response.usage:
                tokens_per_item = response.usage.total_tokens // len(batch)

            for data in response.data:
                results.append(
                    EmbeddingResult(
                        vector=data.embedding,
                        dimensions=len(data.embedding),
                        model=use_model,
                        modality=EmbeddingModality.TEXT,
                        tokens_used=tokens_per_item,
                    )
                )

        return results

    async def embed_image(
        self,
        image_path: str,
        model: str | None = None,
    ) -> EmbeddingResult:
        """Generate embedding for a single image.

        Note: OpenAI doesn't support image embeddings directly.
        Use CLIP or multimodal models instead.
        """
        raise NotImplementedError(
            "OpenAI text embedding models don't support image embeddings. "
            "Use CLIP or a multimodal embedding model instead."
        )

    async def embed_images(
        self,
        image_paths: list[str],
        model: str | None = None,
    ) -> list[EmbeddingResult]:
        """Generate embeddings for multiple images.

        Note: OpenAI doesn't support image embeddings directly.
        """
        raise NotImplementedError(
            "OpenAI text embedding models don't support image embeddings. "
            "Use CLIP or a multimodal embedding model instead."
        )

    @property
    def text_dimensions(self) -> int:
        """Dimensions of text embedding vectors."""
        return self._dimensions

    @property
    def image_dimensions(self) -> int | None:
        """Dimensions of image embedding vectors."""
        return None  # Not supported

    @property
    def supports_text(self) -> bool:
        """Whether this provider supports text embeddings."""
        return True

    @property
    def supports_images(self) -> bool:
        """Whether this provider supports image embeddings."""
        return False

    @property
    def max_batch_size(self) -> int:
        """Maximum batch size for embedding requests."""
        return 2048  # OpenAI limit

    @property
    def max_text_tokens(self) -> int:
        """Maximum tokens per text input."""
        return 8191  # OpenAI limit for embedding models
