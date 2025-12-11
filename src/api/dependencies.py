"""FastAPI dependency injection for services and settings."""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from src.application.services.ingestion import VideoIngestionService
from src.application.services.query import VideoQueryService
from src.commons.settings.loader import get_settings as _load_settings
from src.commons.settings.models import Settings
from src.infrastructure.factory import (
    InfrastructureFactory,
    get_factory,
    reset_factory,
)


@lru_cache
def get_settings() -> Settings:
    """Get cached application settings.

    Returns:
        Application settings loaded from config files and environment.
    """
    return _load_settings()


def get_infrastructure_factory(
    settings: Annotated[Settings, Depends(get_settings)],
) -> InfrastructureFactory:
    """Get infrastructure factory with all providers.

    Args:
        settings: Application settings.

    Returns:
        Configured infrastructure factory.
    """
    return get_factory(settings)


def get_ingestion_service(
    factory: Annotated[InfrastructureFactory, Depends(get_infrastructure_factory)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VideoIngestionService:
    """Get video ingestion service with all dependencies.

    Args:
        factory: Infrastructure factory.
        settings: Application settings.

    Returns:
        Configured video ingestion service.
    """
    return VideoIngestionService(
        youtube_downloader=factory.get_youtube_downloader(),
        transcription_service=factory.get_transcription_service(),
        text_embedding_service=factory.get_text_embedding_service(),
        frame_extractor=factory.get_frame_extractor(),
        blob_storage=factory.get_blob_storage(),
        vector_db=factory.get_vector_db(),
        document_db=factory.get_document_db(),
        settings=settings,
    )


def get_query_service(
    factory: Annotated[InfrastructureFactory, Depends(get_infrastructure_factory)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VideoQueryService:
    """Get video query service with all dependencies.

    Args:
        factory: Infrastructure factory.
        settings: Application settings.

    Returns:
        Configured video query service.
    """
    return VideoQueryService(
        text_embedding_service=factory.get_text_embedding_service(),
        llm_service=factory.get_llm_service(),
        vector_db=factory.get_vector_db(),
        document_db=factory.get_document_db(),
        settings=settings,
        blob_storage=factory.get_blob_storage(),
    )


# Type aliases for cleaner route signatures
SettingsDep = Annotated[Settings, Depends(get_settings)]
FactoryDep = Annotated[InfrastructureFactory, Depends(get_infrastructure_factory)]
IngestionServiceDep = Annotated[VideoIngestionService, Depends(get_ingestion_service)]
QueryServiceDep = Annotated[VideoQueryService, Depends(get_query_service)]


async def init_services(settings: Settings) -> None:
    """Initialize all infrastructure services on startup.

    Args:
        settings: Application settings.
    """
    # Initialize factory with settings
    factory = get_factory(settings)

    # Pre-initialize critical services to fail fast
    factory.get_blob_storage()
    factory.get_vector_db()
    factory.get_document_db()


async def shutdown_services() -> None:
    """Shutdown all infrastructure services."""
    try:
        factory = get_factory()
        await factory.close_all()
    except ValueError:
        pass  # Factory not initialized
    finally:
        reset_factory()
        get_settings.cache_clear()
