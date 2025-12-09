"""CLIP-based image embedding service using external API."""

import base64
import hashlib
from pathlib import Path

import httpx

from src.infrastructure.embeddings.base import (
    EmbeddingModality,
    EmbeddingResult,
    EmbeddingServiceBase,
)


class CLIPEmbeddingService(EmbeddingServiceBase):
    """CLIP-based embedding service for images.

    This implementation connects to an external CLIP embedding API service.
    You can run a CLIP server locally using various implementations:
    - https://github.com/openai/CLIP (official)
    - img2vec services
    - HuggingFace inference endpoints

    The expected API format:
    POST /embed
    Body: {"images": ["base64_image_1", "base64_image_2"]}
    Response: {"embeddings": [[...], [...]]}
    """

    # Default CLIP dimensions
    _DEFAULT_DIMENSIONS = 512  # CLIP ViT-B/32

    def __init__(
        self,
        api_url: str,
        api_key: str | None = None,
        model: str = "clip-vit-base-32",
        dimensions: int = 512,
        timeout: float = 30.0,
    ) -> None:
        """Initialize CLIP embedding client.

        Args:
            api_url: URL to CLIP embedding API.
            api_key: Optional API key for authentication.
            model: Model identifier for tracking.
            dimensions: Vector dimensions for the model.
            timeout: Request timeout in seconds.
        """
        self._api_url = api_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._dimensions = dimensions
        self._timeout = timeout

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(timeout),
        )

    async def embed_text(
        self,
        text: str,
        model: str | None = None,
    ) -> EmbeddingResult:
        """Generate embedding for text using CLIP.

        CLIP can embed text into the same space as images.
        """
        response = await self._client.post(
            f"{self._api_url}/embed/text",
            json={"texts": [text]},
        )
        response.raise_for_status()

        data = response.json()
        embedding = data["embeddings"][0]

        return EmbeddingResult(
            vector=embedding,
            dimensions=len(embedding),
            model=model or self._model,
            modality=EmbeddingModality.TEXT,
            tokens_used=None,
        )

    async def embed_texts(
        self,
        texts: list[str],
        model: str | None = None,
    ) -> list[EmbeddingResult]:
        """Generate embeddings for multiple texts."""
        if not texts:
            return []

        results: list[EmbeddingResult] = []

        for i in range(0, len(texts), self.max_batch_size):
            batch = texts[i : i + self.max_batch_size]

            response = await self._client.post(
                f"{self._api_url}/embed/text",
                json={"texts": batch},
            )
            response.raise_for_status()

            data = response.json()
            for embedding in data["embeddings"]:
                results.append(
                    EmbeddingResult(
                        vector=embedding,
                        dimensions=len(embedding),
                        model=model or self._model,
                        modality=EmbeddingModality.TEXT,
                        tokens_used=None,
                    )
                )

        return results

    async def embed_image(
        self,
        image_path: str,
        model: str | None = None,
    ) -> EmbeddingResult:
        """Generate embedding for a single image."""
        path = Path(image_path)

        with path.open("rb") as f:
            image_bytes = f.read()

        image_b64 = base64.b64encode(image_bytes).decode("utf-8")

        response = await self._client.post(
            f"{self._api_url}/embed/image",
            json={"images": [image_b64]},
        )
        response.raise_for_status()

        data = response.json()
        embedding = data["embeddings"][0]

        return EmbeddingResult(
            vector=embedding,
            dimensions=len(embedding),
            model=model or self._model,
            modality=EmbeddingModality.IMAGE,
            tokens_used=None,
        )

    async def embed_images(
        self,
        image_paths: list[str],
        model: str | None = None,
    ) -> list[EmbeddingResult]:
        """Generate embeddings for multiple images."""
        if not image_paths:
            return []

        results: list[EmbeddingResult] = []

        for i in range(0, len(image_paths), self.max_batch_size):
            batch_paths = image_paths[i : i + self.max_batch_size]

            images_b64: list[str] = []
            for img_path in batch_paths:
                with Path(img_path).open("rb") as f:
                    image_bytes = f.read()
                images_b64.append(base64.b64encode(image_bytes).decode("utf-8"))

            response = await self._client.post(
                f"{self._api_url}/embed/image",
                json={"images": images_b64},
            )
            response.raise_for_status()

            data = response.json()
            for embedding in data["embeddings"]:
                results.append(
                    EmbeddingResult(
                        vector=embedding,
                        dimensions=len(embedding),
                        model=model or self._model,
                        modality=EmbeddingModality.IMAGE,
                        tokens_used=None,
                    )
                )

        return results

    @property
    def text_dimensions(self) -> int:
        """Dimensions of text embedding vectors."""
        return self._dimensions

    @property
    def image_dimensions(self) -> int | None:
        """Dimensions of image embedding vectors."""
        return self._dimensions  # CLIP uses same dimension for both

    @property
    def supports_text(self) -> bool:
        """Whether this provider supports text embeddings."""
        return True  # CLIP supports text-image joint embeddings

    @property
    def supports_images(self) -> bool:
        """Whether this provider supports image embeddings."""
        return True

    @property
    def max_batch_size(self) -> int:
        """Maximum batch size for embedding requests."""
        return 32  # Reasonable default for image processing

    @property
    def max_text_tokens(self) -> int:
        """Maximum tokens per text input."""
        return 77  # CLIP's text encoder limit

    async def close(self) -> None:
        """Close the HTTP client."""
        await self._client.aclose()

    @staticmethod
    def compute_image_hash(image_path: str) -> str:
        """Compute hash of image for caching purposes."""
        with Path(image_path).open("rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
