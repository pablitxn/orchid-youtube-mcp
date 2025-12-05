"""Unit tests for EmbeddingVector model."""

import pytest

from src.domain.models.chunk import Modality
from src.domain.models.embedding import EmbeddingVector


class TestEmbeddingVector:
    """Tests for EmbeddingVector model."""

    @pytest.fixture
    def sample_embedding(self) -> EmbeddingVector:
        return EmbeddingVector(
            chunk_id="chunk-123",
            video_id="video-456",
            modality=Modality.TRANSCRIPT,
            vector=[0.1, 0.2, 0.3, 0.4, 0.5],
            model="text-embedding-3-small",
            dimensions=5,
        )

    def test_create(self, sample_embedding):
        assert sample_embedding.chunk_id == "chunk-123"
        assert sample_embedding.video_id == "video-456"
        assert sample_embedding.modality == Modality.TRANSCRIPT
        assert len(sample_embedding.vector) == 5
        assert sample_embedding.model == "text-embedding-3-small"
        assert sample_embedding.dimensions == 5

    def test_auto_id(self, sample_embedding):
        assert sample_embedding.id is not None
        assert len(sample_embedding.id) == 36

    def test_len(self, sample_embedding):
        assert len(sample_embedding) == 5

    def test_dimensions_must_match_vector_length(self):
        with pytest.raises(ValueError, match="Vector length"):
            EmbeddingVector(
                chunk_id="chunk-123",
                video_id="video-456",
                modality=Modality.TRANSCRIPT,
                vector=[0.1, 0.2, 0.3],
                model="test-model",
                dimensions=5,  # Doesn't match vector length
            )

    def test_is_normalized(self):
        # Create a normalized vector (magnitude = 1)
        import math

        mag = math.sqrt(0.5**2 + 0.5**2 + 0.5**2 + 0.5**2)
        normalized_values = [0.5 / mag] * 4

        normalized = EmbeddingVector(
            chunk_id="chunk-123",
            video_id="video-456",
            modality=Modality.TRANSCRIPT,
            vector=normalized_values,
            model="test-model",
            dimensions=4,
        )
        assert normalized.is_normalized is True

    def test_is_not_normalized(self, sample_embedding):
        assert sample_embedding.is_normalized is False

    def test_normalize(self, sample_embedding):
        normalized = sample_embedding.normalize()
        assert normalized.is_normalized is True
        # Original should be unchanged
        assert sample_embedding.is_normalized is False

    def test_normalize_zero_vector(self):
        zero_vec = EmbeddingVector(
            chunk_id="chunk-123",
            video_id="video-456",
            modality=Modality.TRANSCRIPT,
            vector=[0.0, 0.0, 0.0],
            model="test-model",
            dimensions=3,
        )
        # Should return self without error
        normalized = zero_vec.normalize()
        assert normalized.vector == [0.0, 0.0, 0.0]

    def test_cosine_similarity_identical(self):
        emb1 = EmbeddingVector(
            chunk_id="chunk-1",
            video_id="video-1",
            modality=Modality.TRANSCRIPT,
            vector=[1.0, 0.0, 0.0],
            model="test",
            dimensions=3,
        )
        emb2 = EmbeddingVector(
            chunk_id="chunk-2",
            video_id="video-1",
            modality=Modality.TRANSCRIPT,
            vector=[1.0, 0.0, 0.0],
            model="test",
            dimensions=3,
        )
        assert emb1.cosine_similarity(emb2) == pytest.approx(1.0)

    def test_cosine_similarity_orthogonal(self):
        emb1 = EmbeddingVector(
            chunk_id="chunk-1",
            video_id="video-1",
            modality=Modality.TRANSCRIPT,
            vector=[1.0, 0.0, 0.0],
            model="test",
            dimensions=3,
        )
        emb2 = EmbeddingVector(
            chunk_id="chunk-2",
            video_id="video-1",
            modality=Modality.TRANSCRIPT,
            vector=[0.0, 1.0, 0.0],
            model="test",
            dimensions=3,
        )
        assert emb1.cosine_similarity(emb2) == pytest.approx(0.0)

    def test_cosine_similarity_opposite(self):
        emb1 = EmbeddingVector(
            chunk_id="chunk-1",
            video_id="video-1",
            modality=Modality.TRANSCRIPT,
            vector=[1.0, 0.0, 0.0],
            model="test",
            dimensions=3,
        )
        emb2 = EmbeddingVector(
            chunk_id="chunk-2",
            video_id="video-1",
            modality=Modality.TRANSCRIPT,
            vector=[-1.0, 0.0, 0.0],
            model="test",
            dimensions=3,
        )
        assert emb1.cosine_similarity(emb2) == pytest.approx(-1.0)

    def test_cosine_similarity_dimension_mismatch(self):
        emb1 = EmbeddingVector(
            chunk_id="chunk-1",
            video_id="video-1",
            modality=Modality.TRANSCRIPT,
            vector=[1.0, 0.0, 0.0],
            model="test",
            dimensions=3,
        )
        emb2 = EmbeddingVector(
            chunk_id="chunk-2",
            video_id="video-1",
            modality=Modality.TRANSCRIPT,
            vector=[1.0, 0.0],
            model="test",
            dimensions=2,
        )
        with pytest.raises(ValueError, match="dimensions must match"):
            emb1.cosine_similarity(emb2)

    def test_euclidean_distance_same_point(self):
        emb1 = EmbeddingVector(
            chunk_id="chunk-1",
            video_id="video-1",
            modality=Modality.TRANSCRIPT,
            vector=[1.0, 2.0, 3.0],
            model="test",
            dimensions=3,
        )
        emb2 = EmbeddingVector(
            chunk_id="chunk-2",
            video_id="video-1",
            modality=Modality.TRANSCRIPT,
            vector=[1.0, 2.0, 3.0],
            model="test",
            dimensions=3,
        )
        assert emb1.euclidean_distance(emb2) == pytest.approx(0.0)

    def test_euclidean_distance_different_points(self):
        emb1 = EmbeddingVector(
            chunk_id="chunk-1",
            video_id="video-1",
            modality=Modality.TRANSCRIPT,
            vector=[0.0, 0.0, 0.0],
            model="test",
            dimensions=3,
        )
        emb2 = EmbeddingVector(
            chunk_id="chunk-2",
            video_id="video-1",
            modality=Modality.TRANSCRIPT,
            vector=[3.0, 4.0, 0.0],
            model="test",
            dimensions=3,
        )
        # Distance = sqrt(3^2 + 4^2) = 5
        assert emb1.euclidean_distance(emb2) == pytest.approx(5.0)

    def test_from_values_factory(self):
        emb = EmbeddingVector.from_values(
            chunk_id="chunk-123",
            video_id="video-456",
            modality=Modality.FRAME,
            vector=[0.1, 0.2, 0.3],
            model="clip-vit-b32",
        )
        assert emb.dimensions == 3
        assert emb.chunk_id == "chunk-123"
        assert emb.modality == Modality.FRAME
