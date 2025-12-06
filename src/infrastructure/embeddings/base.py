"""Abstract base class for embedding services."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class EmbeddingModality(str, Enum):
    """Modality of the embedded content."""

    TEXT = "text"
    IMAGE = "image"


@dataclass
class EmbeddingResult:
    """Result from embedding generation."""

    vector: list[float]
    dimensions: int
    model: str
    modality: EmbeddingModality
    tokens_used: int | None = None


class EmbeddingServiceBase(ABC):
    """Abstract base class for embedding generation services.

    Implementations should handle:
    - OpenAI (text embeddings)
    - Azure OpenAI (text embeddings)
    - Cohere (text embeddings)
    - Voyage AI (text embeddings)
    - CLIP (image embeddings)
    - Google Vertex AI (text and image)
    """

    @abstractmethod
    async def embed_text(
        self,
        text: str,
        model: str | None = None,
    ) -> EmbeddingResult:
        """Generate embedding for a single text.

        Args:
            text: Text to embed.
            model: Optional model override.

        Returns:
            Embedding result with vector and metadata.
        """

    @abstractmethod
    async def embed_texts(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[EmbeddingResult]:
        """Generate embeddings for multiple texts (batched).

        Args:
            texts: List of texts to embed.
            model: Optional model override.

        Returns:
            List of embedding results in same order as input.
        """

    @abstractmethod
    async def embed_image(
        self,
        image_path: str,
        model: str | None = None,
    ) -> EmbeddingResult:
        """Generate embedding for a single image.

        Args:
            image_path: Path to the image file.
            model: Optional model override.

        Returns:
            Embedding result with vector and metadata.

        Raises:
            NotImplementedError: If image embeddings not supported.
        """

    @abstractmethod
    async def embed_images(
        self,
        image_paths: list[str],
        model: str | None = None,
    ) -> list[EmbeddingResult]:
        """Generate embeddings for multiple images (batched).

        Args:
            image_paths: List of image file paths.
            model: Optional model override.

        Returns:
            List of embedding results in same order as input.

        Raises:
            NotImplementedError: If image embeddings not supported.
        """

    @property
    @abstractmethod
    def text_dimensions(self) -> int:
        """Dimensions of text embedding vectors.

        Returns:
            Vector dimension size.
        """

    @property
    @abstractmethod
    def image_dimensions(self) -> int | None:
        """Dimensions of image embedding vectors, or None if not supported.

        Returns:
            Vector dimension size or None.
        """

    @property
    @abstractmethod
    def supports_text(self) -> bool:
        """Whether this provider supports text embeddings.

        Returns:
            True if text embeddings are supported.
        """

    @property
    @abstractmethod
    def supports_images(self) -> bool:
        """Whether this provider supports image embeddings.

        Returns:
            True if image embeddings are supported.
        """

    @property
    @abstractmethod
    def max_batch_size(self) -> int:
        """Maximum batch size for embedding requests.

        Returns:
            Maximum number of items per batch request.
        """

    @property
    @abstractmethod
    def max_text_tokens(self) -> int:
        """Maximum tokens per text input.

        Returns:
            Maximum token count.
        """
