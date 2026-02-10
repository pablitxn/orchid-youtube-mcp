"""Infrastructure factory for creating service instances from configuration."""

from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from orchid_commons import ResourceManager

from src.commons.settings.models import Settings
from src.infrastructure.adapters.blob import BlobStorageAdapter
from src.infrastructure.adapters.document import DocumentStoreAdapter
from src.infrastructure.adapters.vector import VectorStoreAdapter
from src.infrastructure.embeddings import (
    CLIPEmbeddingService,
    EmbeddingServiceBase,
    OpenAIEmbeddingService,
)
from src.infrastructure.llm import AnthropicLLMService, LLMServiceBase, OpenAILLMService
from src.infrastructure.transcription import (
    OpenAIWhisperTranscription,
    TranscriptionServiceBase,
)
from src.infrastructure.video import (
    FFmpegFrameExtractor,
    FFmpegVideoChunker,
    FrameExtractorBase,
    VideoChunkerBase,
)
from src.infrastructure.youtube import YouTubeDownloaderBase, YtDlpDownloader

if TYPE_CHECKING:
    from orchid_commons.blob import MultiBucketBlobRouter


class InfrastructureFactory:
    """Factory for creating infrastructure service instances.

    Creates concrete implementations based on configuration settings.
    """

    def __init__(
        self,
        settings: Settings,
        resource_manager: ResourceManager | None = None,
    ) -> None:
        """Initialize factory with settings.

        Args:
            settings: Application settings.
            resource_manager: Optional shared resource manager for lifecycle wiring.
        """
        self._settings = settings
        self._instances: dict[str, Any] = {}
        self._resource_manager = resource_manager
        self._manager_owned_instances: set[str] = set()

    def set_resource_manager(self, resource_manager: ResourceManager) -> None:
        """Attach shared resource manager after factory creation."""
        self._resource_manager = resource_manager

    def get_blob_storage(self) -> BlobStorageAdapter:
        """Get blob storage instance.

        Returns:
            Configured blob storage provider.
        """
        if "blob_storage" not in self._instances:
            if (
                self._resource_manager is not None
                and self._resource_manager.has("multi_bucket")
            ):
                managed_resource = self._resource_manager.get("multi_bucket")
                if isinstance(managed_resource, BlobStorageAdapter):
                    self._instances["blob_storage"] = managed_resource
                else:
                    self._instances["blob_storage"] = BlobStorageAdapter(
                        router=cast("MultiBucketBlobRouter", managed_resource)
                    )
                self._manager_owned_instances.add("blob_storage")
                return cast("BlobStorageAdapter", self._instances["blob_storage"])

            blob_settings = self._settings.blob_storage
            self._instances["blob_storage"] = (
                BlobStorageAdapter.from_settings(
                    endpoint=blob_settings.endpoint,
                    access_key=blob_settings.access_key,
                    secret_key=blob_settings.secret_key,
                    secure=blob_settings.use_ssl,
                    region=blob_settings.region,
                    buckets={
                        "videos": blob_settings.buckets.videos,
                        "chunks": blob_settings.buckets.chunks,
                        "frames": blob_settings.buckets.frames,
                    },
                )
            )
        return cast("BlobStorageAdapter", self._instances["blob_storage"])

    def get_vector_db(self) -> VectorStoreAdapter:
        """Get vector database instance.

        Returns:
            Configured vector database provider.
        """
        if "vector_db" not in self._instances:
            if (
                self._resource_manager is not None
                and self._resource_manager.has("qdrant")
            ):
                managed_resource = self._resource_manager.get("qdrant")
                if isinstance(managed_resource, VectorStoreAdapter):
                    self._instances["vector_db"] = managed_resource
                else:
                    self._instances["vector_db"] = VectorStoreAdapter(
                        managed_resource
                    )
                self._manager_owned_instances.add("vector_db")
                return cast("VectorStoreAdapter", self._instances["vector_db"])

            from orchid_commons.db import QdrantVectorStore

            vector_settings = self._settings.vector_db
            store = QdrantVectorStore.create(
                host=vector_settings.host,
                port=vector_settings.port,
                grpc_port=vector_settings.grpc_port,
                api_key=vector_settings.api_key,
                https=vector_settings.use_ssl,
            )
            self._instances["vector_db"] = VectorStoreAdapter(store)
        return cast("VectorStoreAdapter", self._instances["vector_db"])

    def get_document_db(self) -> DocumentStoreAdapter:
        """Get document database instance.

        Returns:
            Configured document database provider.
        """
        if "document_db" not in self._instances:
            if (
                self._resource_manager is not None
                and self._resource_manager.has("mongodb")
            ):
                managed_resource = self._resource_manager.get("mongodb")
                if isinstance(managed_resource, DocumentStoreAdapter):
                    self._instances["document_db"] = managed_resource
                else:
                    self._instances["document_db"] = DocumentStoreAdapter(
                        managed_resource
                    )
                self._manager_owned_instances.add("document_db")
                return cast("DocumentStoreAdapter", self._instances["document_db"])

            from orchid_commons.db import MongoDbResource

            doc_settings = self._settings.document_db
            if doc_settings.username and doc_settings.password:
                connection_string = (
                    f"mongodb://{doc_settings.username}:{doc_settings.password}"
                    f"@{doc_settings.host}:{doc_settings.port}"
                    f"/?authSource={doc_settings.auth_source}"
                )
            else:
                connection_string = f"mongodb://{doc_settings.host}:{doc_settings.port}"
            resource = MongoDbResource.create(
                uri=connection_string,
                database=doc_settings.database,
            )
            self._instances["document_db"] = DocumentStoreAdapter(resource)
        return cast("DocumentStoreAdapter", self._instances["document_db"])

    def get_youtube_downloader(self) -> YouTubeDownloaderBase:
        """Get YouTube downloader instance.

        Returns:
            Configured YouTube downloader.
        """
        if "youtube_downloader" not in self._instances:
            yt_settings = self._settings.youtube
            cookies_file = (
                Path(yt_settings.cookies_file) if yt_settings.cookies_file else None
            )
            self._instances["youtube_downloader"] = YtDlpDownloader(
                cookies_file=cookies_file,
                cookies_from_browser=yt_settings.cookies_from_browser,
                proxy=yt_settings.proxy,
                rate_limit=yt_settings.rate_limit,
            )
        return cast("YouTubeDownloaderBase", self._instances["youtube_downloader"])

    def get_transcription_service(self) -> TranscriptionServiceBase:
        """Get transcription service instance.

        Returns:
            Configured transcription service.
        """
        if "transcription" not in self._instances:
            trans_settings = self._settings.transcription
            self._instances["transcription"] = OpenAIWhisperTranscription(
                api_key=trans_settings.api_key,
                model=trans_settings.model,
            )
        return cast("TranscriptionServiceBase", self._instances["transcription"])

    def get_text_embedding_service(self) -> EmbeddingServiceBase:
        """Get text embedding service instance.

        Returns:
            Configured text embedding service.
        """
        if "text_embedding" not in self._instances:
            embed_settings = self._settings.embeddings.text
            self._instances["text_embedding"] = OpenAIEmbeddingService(
                api_key=embed_settings.api_key,
                model=embed_settings.model,
            )
        return cast("EmbeddingServiceBase", self._instances["text_embedding"])

    def get_image_embedding_service(self) -> EmbeddingServiceBase:
        """Get image embedding service instance.

        Returns:
            Configured image embedding service.
        """
        if "image_embedding" not in self._instances:
            embed_settings = self._settings.embeddings.image
            self._instances["image_embedding"] = CLIPEmbeddingService(
                api_url=embed_settings.api_url,
                api_key=embed_settings.api_key,
                model=embed_settings.model,
                dimensions=embed_settings.dimensions,
            )
        return cast("EmbeddingServiceBase", self._instances["image_embedding"])

    def get_llm_service(self) -> LLMServiceBase:
        """Get LLM service instance.

        Returns:
            Configured LLM service.

        Raises:
            ValueError: If provider is not supported.
        """
        if "llm" not in self._instances:
            llm_settings = self._settings.llm
            provider = llm_settings.provider

            if provider == "anthropic":
                self._instances["llm"] = AnthropicLLMService(
                    api_key=llm_settings.api_key,
                    model=llm_settings.model,
                    base_url=llm_settings.endpoint,
                )
            elif provider in ("openai", "azure_openai"):
                self._instances["llm"] = OpenAILLMService(
                    api_key=llm_settings.api_key,
                    model=llm_settings.model,
                    base_url=llm_settings.endpoint,
                )
            else:
                raise ValueError(f"Unsupported LLM provider: {provider}")

        return cast("LLMServiceBase", self._instances["llm"])

    def get_frame_extractor(self) -> FrameExtractorBase:
        """Get frame extractor instance.

        Returns:
            Configured frame extractor.
        """
        if "frame_extractor" not in self._instances:
            self._instances["frame_extractor"] = FFmpegFrameExtractor()
        return cast("FrameExtractorBase", self._instances["frame_extractor"])

    def get_video_chunker(self) -> VideoChunkerBase:
        """Get video chunker instance.

        Returns:
            Configured video chunker.
        """
        if "video_chunker" not in self._instances:
            self._instances["video_chunker"] = FFmpegVideoChunker()
        return cast("VideoChunkerBase", self._instances["video_chunker"])

    async def close_all(self) -> None:
        """Close all service connections."""
        # Close services that have close methods
        for name, instance in self._instances.items():
            # Runtime-managed resources are closed by ResourceManager lifecycle.
            if name in self._manager_owned_instances:
                continue

            if hasattr(instance, "close"):
                try:
                    close_result = instance.close()
                    if hasattr(close_result, "__await__"):
                        await close_result
                except Exception:
                    pass  # Ignore close errors

        self._instances.clear()
        self._manager_owned_instances.clear()


class _FactoryHolder:
    """Holder for the factory singleton to avoid global statements."""

    instance: InfrastructureFactory | None = None


def get_factory(
    settings: Settings | None = None,
    *,
    resource_manager: ResourceManager | None = None,
) -> InfrastructureFactory:
    """Get or create the infrastructure factory singleton.

    Args:
        settings: Settings to use. Required on first call.

    Returns:
        Infrastructure factory instance.

    Raises:
        ValueError: If settings not provided on first call.
    """
    if _FactoryHolder.instance is None:
        if settings is None:
            raise ValueError("Settings required to initialize factory")
        _FactoryHolder.instance = InfrastructureFactory(
            settings,
            resource_manager=resource_manager,
        )
    elif resource_manager is not None:
        _FactoryHolder.instance.set_resource_manager(resource_manager)

    return _FactoryHolder.instance


def reset_factory() -> None:
    """Reset the factory singleton (for testing)."""
    _FactoryHolder.instance = None
