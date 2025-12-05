"""Embedding domain model for vector representations."""

import math
from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, computed_field, model_validator

from src.domain.models.chunk import Modality


class EmbeddingVector(BaseModel):
    """A vector embedding associated with a chunk.

    Embeddings are stored in the vector database and used
    for semantic similarity search.
    """

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        description="Unique embedding identifier",
    )
    chunk_id: str = Field(description="Reference to source chunk")
    video_id: str = Field(
        description="Reference to parent video (denormalized for query efficiency)",
    )
    modality: Modality = Field(description="Modality of the source chunk")
    vector: list[float] = Field(description="The embedding vector")
    model: str = Field(description="Model used to generate this embedding")
    dimensions: int = Field(gt=0, description="Vector dimensionality")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="When this embedding was created",
    )

    @model_validator(mode="after")
    def validate_dimensions(self) -> "EmbeddingVector":
        """Ensure dimensions matches vector length."""
        if len(self.vector) != self.dimensions:
            msg = (
                f"Vector length ({len(self.vector)}) "
                f"must match dimensions ({self.dimensions})"
            )
            raise ValueError(msg)
        return self

    def __len__(self) -> int:
        """Return vector length."""
        return len(self.vector)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_normalized(self) -> bool:
        """Check if vector is L2 normalized (magnitude ≈ 1).

        Returns:
            True if vector magnitude is close to 1.0.
        """
        magnitude = math.sqrt(sum(x * x for x in self.vector))
        return bool(abs(magnitude - 1.0) < 0.01)

    def normalize(self) -> "EmbeddingVector":
        """Create a normalized copy of this embedding.

        Returns:
            New EmbeddingVector with L2 normalized vector.
        """
        magnitude = math.sqrt(sum(x * x for x in self.vector))
        if magnitude == 0:
            return self
        normalized_vector = [x / magnitude for x in self.vector]
        return self.model_copy(update={"vector": normalized_vector})

    def cosine_similarity(self, other: "EmbeddingVector") -> float:
        """Calculate cosine similarity with another embedding.

        Args:
            other: Another embedding to compare with.

        Returns:
            Cosine similarity score between -1 and 1.

        Raises:
            ValueError: If vectors have different dimensions.
        """
        if len(self.vector) != len(other.vector):
            msg = (
                f"Vector dimensions must match: "
                f"{len(self.vector)} vs {len(other.vector)}"
            )
            raise ValueError(msg)

        dot_product: float = sum(
            a * b for a, b in zip(self.vector, other.vector, strict=True)
        )
        magnitude_a = math.sqrt(sum(x * x for x in self.vector))
        magnitude_b = math.sqrt(sum(x * x for x in other.vector))

        if magnitude_a == 0 or magnitude_b == 0:
            return 0.0

        return float(dot_product / (magnitude_a * magnitude_b))

    def euclidean_distance(self, other: "EmbeddingVector") -> float:
        """Calculate Euclidean distance to another embedding.

        Args:
            other: Another embedding to compare with.

        Returns:
            Euclidean distance (lower is more similar).

        Raises:
            ValueError: If vectors have different dimensions.
        """
        if len(self.vector) != len(other.vector):
            msg = (
                f"Vector dimensions must match: "
                f"{len(self.vector)} vs {len(other.vector)}"
            )
            raise ValueError(msg)

        squared_sum: float = sum(
            (a - b) ** 2 for a, b in zip(self.vector, other.vector, strict=True)
        )
        return math.sqrt(squared_sum)

    @classmethod
    def from_values(
        cls,
        *,
        chunk_id: str,
        video_id: str,
        modality: Modality,
        vector: list[float],
        model: str,
    ) -> "EmbeddingVector":
        """Create an embedding with automatic dimension calculation.

        Args:
            chunk_id: Reference to source chunk.
            video_id: Reference to parent video.
            modality: Modality of the source chunk.
            vector: The embedding vector.
            model: Model used to generate this embedding.

        Returns:
            New EmbeddingVector instance.
        """
        return cls(
            chunk_id=chunk_id,
            video_id=video_id,
            modality=modality,
            vector=vector,
            model=model,
            dimensions=len(vector),
        )
