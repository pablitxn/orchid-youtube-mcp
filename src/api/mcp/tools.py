"""MCP tool implementations for YouTube RAG Server."""

from typing import Any

from src.application.dtos.ingestion import IngestVideoRequest
from src.application.dtos.query import (
    GetSourcesRequest,
    QueryModality,
    QueryVideoRequest,
)
from src.application.services.ingestion import VideoIngestionService
from src.application.services.query import VideoQueryService
from src.commons.settings.models import Settings
from src.domain.models.video import VideoStatus
from src.infrastructure.factory import InfrastructureFactory


def _create_ingestion_service(
    factory: InfrastructureFactory,
    settings: Settings,
) -> VideoIngestionService:
    """Create video ingestion service from factory."""
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


def _create_query_service(
    factory: InfrastructureFactory,
    settings: Settings,
) -> VideoQueryService:
    """Create video query service from factory."""
    return VideoQueryService(
        text_embedding_service=factory.get_text_embedding_service(),
        llm_service=factory.get_llm_service(),
        vector_db=factory.get_vector_db(),
        document_db=factory.get_document_db(),
        settings=settings,
        blob_storage=factory.get_blob_storage(),
    )


async def ingest_video_tool(
    factory: InfrastructureFactory,
    settings: Settings,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Ingest a YouTube video.

    Args:
        factory: Infrastructure factory.
        settings: Application settings.
        arguments: Tool arguments from MCP.

    Returns:
        Ingestion result dictionary.
    """
    service = _create_ingestion_service(factory, settings)

    request = IngestVideoRequest(
        url=arguments["youtube_url"],
        language_hint=arguments.get("language_hint"),
        extract_frames=arguments.get("extract_frames", True),
        extract_audio_chunks=arguments.get("extract_audio_chunks", False),
        extract_video_chunks=arguments.get("extract_video_chunks", False),
    )

    result = await service.ingest(request)

    return {
        "video_id": result.video_id,
        "youtube_id": result.youtube_id,
        "title": result.title,
        "duration_seconds": result.duration_seconds,
        "status": result.status.value,
        "message": "Ingestion started. Use get_ingestion_status to track.",
    }


async def get_ingestion_status_tool(
    factory: InfrastructureFactory,
    settings: Settings,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Get ingestion status for a video.

    Args:
        factory: Infrastructure factory.
        settings: Application settings.
        arguments: Tool arguments from MCP.

    Returns:
        Status dictionary.
    """
    service = _create_ingestion_service(factory, settings)

    video_id = arguments["video_id"]
    result = await service.get_ingestion_status(video_id)

    if result is None:
        return {
            "error": f"Video with ID '{video_id}' was not found",
            "video_id": video_id,
        }

    return {
        "video_id": result.video_id,
        "youtube_id": result.youtube_id,
        "title": result.title,
        "status": result.status.value,
        "chunk_counts": result.chunk_counts,
        "error_message": result.error_message,
    }


async def query_video_tool(
    factory: InfrastructureFactory,
    settings: Settings,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Query video content.

    Args:
        factory: Infrastructure factory.
        settings: Application settings.
        arguments: Tool arguments from MCP.

    Returns:
        Query result dictionary.
    """
    service = _create_query_service(factory, settings)

    # Parse modalities
    modality_strs = arguments.get("modalities", ["transcript", "frame"])
    modalities = [QueryModality(m) for m in modality_strs]

    request = QueryVideoRequest(
        query=arguments["query"],
        modalities=modalities,
        max_citations=arguments.get("max_citations", 5),
        include_reasoning=True,
    )

    try:
        result = await service.query(arguments["video_id"], request)

        return {
            "answer": result.answer,
            "reasoning": result.reasoning,
            "confidence": result.confidence,
            "citations": [
                {
                    "id": c.id,
                    "modality": c.modality.value,
                    "timestamp_range": {
                        "start_time": c.timestamp_range.start_time,
                        "end_time": c.timestamp_range.end_time,
                        "display": c.timestamp_range.display,
                    },
                    "content_preview": c.content_preview,
                    "relevance_score": c.relevance_score,
                    "youtube_url": c.youtube_url,
                }
                for c in result.citations
            ],
            "query_metadata": {
                "video_id": result.query_metadata.video_id,
                "video_title": result.query_metadata.video_title,
                "modalities_searched": [
                    m.value for m in result.query_metadata.modalities_searched
                ],
                "chunks_analyzed": result.query_metadata.chunks_analyzed,
                "processing_time_ms": result.query_metadata.processing_time_ms,
            },
        }
    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            return {
                "error": f"Video with ID '{arguments['video_id']}' was not found",
                "video_id": arguments["video_id"],
            }
        if "not ready" in error_msg.lower():
            return {
                "error": "Video is still being processed",
                "video_id": arguments["video_id"],
            }
        return {"error": error_msg}


async def get_sources_tool(
    factory: InfrastructureFactory,
    settings: Settings,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Get source artifacts for citations.

    Args:
        factory: Infrastructure factory.
        settings: Application settings.
        arguments: Tool arguments from MCP.

    Returns:
        Sources dictionary.
    """
    service = _create_query_service(factory, settings)

    request = GetSourcesRequest(
        citation_ids=arguments["citation_ids"],
        include_artifacts=arguments.get(
            "include_artifacts", ["transcript_text", "thumbnail"]
        ),
        url_expiry_minutes=60,
    )

    try:
        result = await service.get_sources(arguments["video_id"], request)

        return {
            "sources": [
                {
                    "citation_id": s.citation_id,
                    "modality": s.modality.value,
                    "timestamp_range": {
                        "start_time": s.timestamp_range.start_time,
                        "end_time": s.timestamp_range.end_time,
                        "display": s.timestamp_range.display,
                    },
                    "artifacts": {
                        k: {"type": v.type, "url": v.url, "content": v.content}
                        for k, v in s.artifacts.items()
                    },
                }
                for s in result.sources
            ],
            "expires_at": result.expires_at.isoformat(),
        }
    except ValueError as e:
        return {"error": str(e), "video_id": arguments["video_id"]}


async def list_videos_tool(
    factory: InfrastructureFactory,
    settings: Settings,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """List indexed videos.

    Args:
        factory: Infrastructure factory.
        settings: Application settings.
        arguments: Tool arguments from MCP.

    Returns:
        Videos list dictionary.
    """
    service = _create_ingestion_service(factory, settings)

    # Parse status filter
    status_filter: VideoStatus | None = None
    if "status" in arguments:
        status_map = {
            "ready": VideoStatus.READY,
            "processing": VideoStatus.DOWNLOADING,
            "failed": VideoStatus.FAILED,
            "pending": VideoStatus.PENDING,
        }
        status_filter = status_map.get(arguments["status"].lower())

    page = arguments.get("page", 1)
    page_size = arguments.get("page_size", 20)
    skip = (page - 1) * page_size

    videos = await service.list_videos(
        status=status_filter,
        skip=skip,
        limit=page_size,
    )

    return {
        "videos": [
            {
                "id": v.video_id,
                "youtube_id": v.youtube_id,
                "title": v.title,
                "duration_seconds": v.duration_seconds,
                "status": v.status.value,
                "chunk_counts": v.chunk_counts,
                "created_at": v.created_at.isoformat(),
            }
            for v in videos
        ],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": len(videos) + skip,
        },
    }


async def delete_video_tool(
    factory: InfrastructureFactory,
    settings: Settings,
    arguments: dict[str, Any],
) -> dict[str, Any]:
    """Delete a video and all associated data.

    Args:
        factory: Infrastructure factory.
        settings: Application settings.
        arguments: Tool arguments from MCP.

    Returns:
        Deletion result dictionary.
    """
    service = _create_ingestion_service(factory, settings)

    video_id = arguments["video_id"]
    confirm = arguments.get("confirm", False)

    if not confirm:
        return {
            "error": "Deletion requires confirm=true",
            "video_id": video_id,
        }

    # Check if video exists
    existing = await service.get_ingestion_status(video_id)
    if existing is None:
        return {
            "error": f"Video with ID '{video_id}' was not found",
            "video_id": video_id,
        }

    # Delete the video
    deleted = await service.delete_video(video_id)

    if not deleted:
        return {
            "error": "Failed to delete video",
            "video_id": video_id,
        }

    return {
        "success": True,
        "video_id": video_id,
        "message": "Video and all associated data deleted successfully",
    }
