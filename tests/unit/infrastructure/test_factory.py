"""Unit tests for infrastructure factory."""

from unittest.mock import MagicMock, patch

import pytest

from src.infrastructure.factory import (
    InfrastructureFactory,
    get_factory,
    reset_factory,
)


@pytest.fixture(autouse=True)
def reset_factory_before_each():
    """Reset factory singleton before each test."""
    reset_factory()
    yield
    reset_factory()


@pytest.fixture
def mock_settings():
    """Create mock settings."""
    settings = MagicMock()

    # Blob storage settings
    settings.blob_storage.endpoint = "localhost:9000"
    settings.blob_storage.access_key = "minioadmin"
    settings.blob_storage.secret_key = "minioadmin"
    settings.blob_storage.use_ssl = False
    settings.blob_storage.region = "us-east-1"

    # Vector DB settings
    settings.vector_db.host = "localhost"
    settings.vector_db.port = 6333
    settings.vector_db.grpc_port = 6334
    settings.vector_db.api_key = None

    # Document DB settings
    settings.document_db.host = "localhost"
    settings.document_db.port = 27017
    settings.document_db.username = ""
    settings.document_db.password = ""
    settings.document_db.database = "test_db"
    settings.document_db.auth_source = "admin"

    # Transcription settings
    settings.transcription.api_key = "test-key"
    settings.transcription.model = "whisper-1"

    # Embedding settings
    settings.embeddings.text.api_key = "test-key"
    settings.embeddings.text.model = "text-embedding-3-small"
    settings.embeddings.image.api_url = "http://localhost:8080"
    settings.embeddings.image.api_key = None
    settings.embeddings.image.model = "ViT-B/32"
    settings.embeddings.image.dimensions = 512

    # LLM settings
    settings.llm.provider = "openai"
    settings.llm.api_key = "test-key"
    settings.llm.model = "gpt-4o"
    settings.llm.endpoint = None

    return settings


class TestInfrastructureFactory:
    """Tests for InfrastructureFactory."""

    def test_factory_init(self, mock_settings):
        """Test factory initialization."""
        factory = InfrastructureFactory(mock_settings)
        assert factory._settings is mock_settings
        assert factory._instances == {}

    def test_get_youtube_downloader(self, mock_settings):
        """Test getting YouTube downloader."""
        factory = InfrastructureFactory(mock_settings)
        downloader = factory.get_youtube_downloader()

        assert downloader is not None
        # Should return same instance on second call
        assert factory.get_youtube_downloader() is downloader

    def test_get_frame_extractor(self, mock_settings):
        """Test getting frame extractor."""
        factory = InfrastructureFactory(mock_settings)
        extractor = factory.get_frame_extractor()

        assert extractor is not None
        assert factory.get_frame_extractor() is extractor

    def test_get_video_chunker(self, mock_settings):
        """Test getting video chunker."""
        factory = InfrastructureFactory(mock_settings)
        chunker = factory.get_video_chunker()

        assert chunker is not None
        assert factory.get_video_chunker() is chunker

    @patch("src.infrastructure.factory.MinioBlobStorage")
    def test_get_blob_storage(self, mock_minio_class, mock_settings):
        """Test getting blob storage."""
        mock_instance = MagicMock()
        mock_minio_class.return_value = mock_instance

        factory = InfrastructureFactory(mock_settings)
        blob = factory.get_blob_storage()

        assert blob is mock_instance
        mock_minio_class.assert_called_once_with(
            endpoint="localhost:9000",
            access_key="minioadmin",
            secret_key="minioadmin",
            secure=False,
            region="us-east-1",
        )

    @patch("src.infrastructure.factory.MinioBlobStorage")
    def test_get_blob_storage_from_resource_manager(
        self,
        mock_minio_class,
        mock_settings,
    ):
        """Test blob storage is reused from ResourceManager when available."""
        manager = MagicMock()
        manager.has.side_effect = lambda name: name == "minio"
        manager_blob = MagicMock()
        manager.get.return_value = manager_blob

        factory = InfrastructureFactory(mock_settings, resource_manager=manager)
        blob = factory.get_blob_storage()

        assert blob is manager_blob
        mock_minio_class.assert_not_called()
        manager.get.assert_called_once_with("minio")

    @patch("src.infrastructure.factory.QdrantVectorDB")
    def test_get_vector_db(self, mock_qdrant_class, mock_settings):
        """Test getting vector database."""
        mock_instance = MagicMock()
        mock_qdrant_class.return_value = mock_instance

        factory = InfrastructureFactory(mock_settings)
        vector_db = factory.get_vector_db()

        assert vector_db is mock_instance
        mock_qdrant_class.assert_called_once()

    @patch("src.infrastructure.factory.QdrantVectorDB")
    def test_get_vector_db_from_resource_manager(
        self,
        mock_qdrant_class,
        mock_settings,
    ):
        """Test vector db is reused from ResourceManager when available."""
        manager = MagicMock()
        manager.has.side_effect = lambda name: name == "qdrant"
        manager_vector = MagicMock()
        manager.get.return_value = manager_vector

        factory = InfrastructureFactory(mock_settings, resource_manager=manager)
        vector_db = factory.get_vector_db()

        assert vector_db is manager_vector
        mock_qdrant_class.assert_not_called()
        manager.get.assert_called_once_with("qdrant")

    @patch("src.infrastructure.factory.MongoDBDocumentDB")
    def test_get_document_db_without_auth(self, mock_mongo_class, mock_settings):
        """Test getting document database without authentication."""
        mock_instance = MagicMock()
        mock_mongo_class.return_value = mock_instance

        factory = InfrastructureFactory(mock_settings)
        doc_db = factory.get_document_db()

        assert doc_db is mock_instance
        mock_mongo_class.assert_called_once_with(
            connection_string="mongodb://localhost:27017",
            database_name="test_db",
        )

    @patch("src.infrastructure.factory.MongoDBDocumentDB")
    def test_get_document_db_with_auth(self, mock_mongo_class, mock_settings):
        """Test getting document database with authentication."""
        mock_settings.document_db.username = "user"
        mock_settings.document_db.password = "pass"

        mock_instance = MagicMock()
        mock_mongo_class.return_value = mock_instance

        factory = InfrastructureFactory(mock_settings)
        doc_db = factory.get_document_db()

        assert doc_db is mock_instance
        call_args = mock_mongo_class.call_args
        assert "user:pass" in call_args.kwargs["connection_string"]

    @patch("src.infrastructure.factory.MongoDBDocumentDB")
    def test_get_document_db_from_resource_manager(
        self,
        mock_mongo_class,
        mock_settings,
    ):
        """Test document db is reused from ResourceManager when available."""
        manager = MagicMock()
        manager.has.side_effect = lambda name: name == "mongodb"
        manager_doc_db = MagicMock()
        manager.get.return_value = manager_doc_db

        factory = InfrastructureFactory(mock_settings, resource_manager=manager)
        document_db = factory.get_document_db()

        assert document_db is manager_doc_db
        mock_mongo_class.assert_not_called()
        manager.get.assert_called_once_with("mongodb")

    @patch("src.infrastructure.factory.OpenAIWhisperTranscription")
    def test_get_transcription_service(self, mock_whisper_class, mock_settings):
        """Test getting transcription service."""
        mock_instance = MagicMock()
        mock_whisper_class.return_value = mock_instance

        factory = InfrastructureFactory(mock_settings)
        transcriber = factory.get_transcription_service()

        assert transcriber is mock_instance
        mock_whisper_class.assert_called_once_with(
            api_key="test-key",
            model="whisper-1",
        )

    @patch("src.infrastructure.factory.OpenAIEmbeddingService")
    def test_get_text_embedding_service(self, mock_embed_class, mock_settings):
        """Test getting text embedding service."""
        mock_instance = MagicMock()
        mock_embed_class.return_value = mock_instance

        factory = InfrastructureFactory(mock_settings)
        embedder = factory.get_text_embedding_service()

        assert embedder is mock_instance

    @patch("src.infrastructure.factory.CLIPEmbeddingService")
    def test_get_image_embedding_service(self, mock_clip_class, mock_settings):
        """Test getting image embedding service."""
        mock_instance = MagicMock()
        mock_clip_class.return_value = mock_instance

        factory = InfrastructureFactory(mock_settings)
        embedder = factory.get_image_embedding_service()

        assert embedder is mock_instance

    @patch("src.infrastructure.factory.OpenAILLMService")
    def test_get_llm_service_openai(self, mock_llm_class, mock_settings):
        """Test getting OpenAI LLM service."""
        mock_instance = MagicMock()
        mock_llm_class.return_value = mock_instance

        factory = InfrastructureFactory(mock_settings)
        llm = factory.get_llm_service()

        assert llm is mock_instance

    @patch("src.infrastructure.factory.AnthropicLLMService")
    def test_get_llm_service_anthropic(self, mock_llm_class, mock_settings):
        """Test getting Anthropic LLM service."""
        mock_settings.llm.provider = "anthropic"
        mock_instance = MagicMock()
        mock_llm_class.return_value = mock_instance

        factory = InfrastructureFactory(mock_settings)
        llm = factory.get_llm_service()

        assert llm is mock_instance

    def test_get_llm_service_unsupported_provider(self, mock_settings):
        """Test getting LLM service with unsupported provider."""
        mock_settings.llm.provider = "unsupported"

        factory = InfrastructureFactory(mock_settings)

        with pytest.raises(ValueError, match="Unsupported LLM provider"):
            factory.get_llm_service()

    async def test_close_all(self, mock_settings):
        """Test closing all services."""
        factory = InfrastructureFactory(mock_settings)

        # Add mock instances
        mock_service = MagicMock()
        mock_service.close = MagicMock()
        factory._instances["test"] = mock_service

        await factory.close_all()

        mock_service.close.assert_called_once()
        assert factory._instances == {}

    async def test_close_all_skips_resource_manager_owned_instances(
        self,
        mock_settings,
    ):
        """Test manager-owned resources are not closed by the factory."""
        factory = InfrastructureFactory(mock_settings)

        manager_owned = MagicMock()
        manager_owned.close = MagicMock()
        local_owned = MagicMock()
        local_owned.close = MagicMock()

        factory._instances["blob_storage"] = manager_owned
        factory._instances["other"] = local_owned
        factory._manager_owned_instances.add("blob_storage")

        await factory.close_all()

        manager_owned.close.assert_not_called()
        local_owned.close.assert_called_once()


class TestFactorySingleton:
    """Tests for factory singleton functions."""

    def test_get_factory_requires_settings_first_call(self):
        """Test that settings are required on first call."""
        with pytest.raises(ValueError, match="Settings required"):
            get_factory()

    def test_get_factory_with_settings(self, mock_settings):
        """Test getting factory with settings."""
        factory = get_factory(mock_settings)
        assert factory is not None

    def test_get_factory_returns_same_instance(self, mock_settings):
        """Test that same instance is returned."""
        factory1 = get_factory(mock_settings)
        factory2 = get_factory()  # No settings needed now

        assert factory1 is factory2

    def test_get_factory_can_attach_resource_manager(self, mock_settings):
        """Test attaching a manager to an existing factory singleton."""
        factory = get_factory(mock_settings)
        manager = MagicMock()

        same_factory = get_factory(resource_manager=manager)

        assert same_factory is factory
        assert same_factory._resource_manager is manager

    def test_reset_factory(self, mock_settings):
        """Test factory reset."""
        factory1 = get_factory(mock_settings)
        reset_factory()

        # Now should require settings again
        with pytest.raises(ValueError):
            get_factory()

        # Can create new factory
        factory2 = get_factory(mock_settings)
        assert factory1 is not factory2
