"""Administrative inspection endpoints for the human UI."""

import re
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Query, status
from orchid_commons import APIError
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask
from starlette.responses import FileResponse

from src.adapters.dependencies import (
    FactoryDep,
    SettingsDep,
    StorageServiceDep,
    YouTubeAuthServiceDep,
)
from src.application.dtos.ingestion import IngestionStatus
from src.application.dtos.youtube_auth import (
    AudioDownloadPreset,
    YouTubeAuthStatus,
    YouTubeDownloadTestResult,
)
from src.application.services.storage import VideoStorageService
from src.domain.models.chunk import (
    AudioChunk,
    BaseChunk,
    FrameChunk,
    Modality,
    TranscriptChunk,
    VideoChunk,
)
from src.domain.models.video import VideoMetadata, VideoStatus
from src.infrastructure.youtube.downloader import DownloadError, VideoNotFoundError

router = APIRouter()
_DOWNLOAD_FILENAME_PATTERN = re.compile(r"[^A-Za-z0-9]+")


class AdminArtifactResponse(BaseModel):
    """Artifact metadata for admin inspection views."""

    type: str = Field(description="Artifact type identifier")
    label: str = Field(description="Human-friendly artifact label")
    bucket: str | None = Field(default=None, description="Source bucket alias")
    path: str | None = Field(default=None, description="Blob path if applicable")
    url: str | None = Field(default=None, description="Presigned or external URL")
    content: str | None = Field(
        default=None,
        description="Inline textual content when applicable",
    )


class AdminOverviewResponse(BaseModel):
    """High-level inventory for the personal admin UI."""

    total_videos: int = Field(ge=0, description="Total indexed videos")
    videos_by_status: dict[str, int] = Field(
        default_factory=dict,
        description="Counts by user-facing ingestion status",
    )
    videos_by_processing_state: dict[str, int] = Field(
        default_factory=dict,
        description="Counts by internal processing state",
    )
    total_chunks: int = Field(ge=0, description="Total indexed chunks")
    chunks_by_modality: dict[str, int] = Field(
        default_factory=dict,
        description="Indexed chunks by modality",
    )
    latest_ingestion_at: datetime | None = Field(
        default=None,
        description="Timestamp of the most recently ingested video",
    )


class AdminVideoDetailResponse(BaseModel):
    """Detailed video metadata for the admin UI."""

    id: str = Field(description="Internal video UUID")
    youtube_id: str = Field(description="YouTube video ID")
    youtube_url: str = Field(description="Canonical YouTube URL")
    title: str = Field(description="Video title")
    description: str = Field(description="YouTube description")
    duration_seconds: int = Field(description="Video duration in seconds")
    duration_display: str = Field(description="Preformatted duration")
    status: IngestionStatus = Field(description="User-facing ingestion status")
    processing_state: VideoStatus = Field(description="Detailed processing state")
    chunk_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Chunk counts by modality",
    )
    total_chunks: int = Field(description="Total chunks across modalities")
    created_at: datetime = Field(description="When the video was indexed")
    updated_at: datetime = Field(description="Last metadata update")
    upload_date: datetime = Field(description="Original YouTube upload date")
    channel_name: str = Field(description="YouTube channel name")
    channel_id: str = Field(description="YouTube channel ID")
    thumbnail_url: str = Field(description="Original YouTube thumbnail URL")
    language: str | None = Field(default=None, description="Detected language")
    error_message: str | None = Field(
        default=None,
        description="Failure details when processing failed",
    )
    artifacts: list[AdminArtifactResponse] = Field(
        default_factory=list,
        description="Direct links to saved original media",
    )


class AdminChunkResponse(BaseModel):
    """Chunk metadata for timeline/index inspection."""

    id: str = Field(description="Chunk UUID")
    modality: Modality = Field(description="Chunk modality")
    start_time: float = Field(ge=0, description="Chunk start time")
    end_time: float = Field(ge=0, description="Chunk end time")
    duration_seconds: float = Field(ge=0, description="Chunk duration")
    timestamp: str = Field(description="Human-friendly timestamp range")
    youtube_url: str = Field(description="Timestamped YouTube URL")
    preview: str = Field(description="Best-effort content preview")
    created_at: datetime = Field(description="When the chunk was created")
    metadata: dict[str, str | int | float | bool | None] = Field(
        default_factory=dict,
        description="Chunk-specific metadata for rendering",
    )
    artifacts: list[AdminArtifactResponse] = Field(
        default_factory=list,
        description="Accessible artifacts for this chunk",
    )


class ChunkPaginationResponse(BaseModel):
    """Pagination metadata for chunk listings."""

    offset: int = Field(ge=0, description="Current offset")
    limit: int = Field(ge=1, description="Requested page size")
    total_items: int = Field(ge=0, description="Total available items")


class AdminChunksResponse(BaseModel):
    """Response containing indexed chunks for a video."""

    video_id: str = Field(description="Video identifier")
    modality: Modality | None = Field(
        default=None,
        description="Applied modality filter, or null for all",
    )
    chunk_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Chunk counts by modality for the parent video",
    )
    pagination: ChunkPaginationResponse = Field(description="Pagination metadata")
    chunks: list[AdminChunkResponse] = Field(description="Chunk list")


class UpdateYouTubeCookieRequest(BaseModel):
    """Request model for saving a managed yt-dlp cookies.txt."""

    cookie_text: str = Field(
        min_length=1,
        max_length=200_000,
        description="Full Netscape cookies.txt export content",
    )
    source_label: str | None = Field(
        default=None,
        max_length=120,
        description="Optional operator label for the pasted cookie",
    )


class BrowserAudioDownloadRequest(BaseModel):
    """Request model for browser-delivered audio-only downloads."""

    youtube_url: str = Field(
        min_length=1,
        description="YouTube URL to fetch as audio-only media",
        examples=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )
    preset: AudioDownloadPreset = Field(
        default=AudioDownloadPreset.MP3_192,
        description="Audio download preset",
    )


class YouTubeDownloadTestRequest(BaseModel):
    """Request model for running an ephemeral yt-dlp download diagnostic."""

    youtube_url: str = Field(
        min_length=1,
        description="YouTube URL to test with the currently active auth state",
        examples=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )


@router.get(
    "/admin/overview",
    response_model=AdminOverviewResponse,
    summary="Get admin overview",
    description="Return high-level counts for the human admin interface.",
)
async def get_admin_overview(
    storage: StorageServiceDep,
    factory: FactoryDep,
    settings: SettingsDep,
) -> AdminOverviewResponse:
    """Get the personal dashboard overview."""
    document_db = factory.get_document_db()
    videos_collection = settings.document_db.collections.videos
    status_counts: dict[str, int] = {}
    processing_state_counts: dict[str, int] = {}

    for processing_state in VideoStatus:
        count = await document_db.count(
            videos_collection,
            {"status": processing_state.value},
        )
        processing_state_counts[processing_state.value] = count

    status_counts[IngestionStatus.PENDING.value] = processing_state_counts.get(
        VideoStatus.PENDING.value,
        0,
    )
    status_counts[IngestionStatus.IN_PROGRESS.value] = sum(
        processing_state_counts.get(state.value, 0)
        for state in (
            VideoStatus.DOWNLOADING,
            VideoStatus.TRANSCRIBING,
            VideoStatus.EXTRACTING,
            VideoStatus.EMBEDDING,
        )
    )
    status_counts[IngestionStatus.COMPLETED.value] = processing_state_counts.get(
        VideoStatus.READY.value,
        0,
    )
    status_counts[IngestionStatus.FAILED.value] = processing_state_counts.get(
        VideoStatus.FAILED.value,
        0,
    )

    chunk_collection_map = {
        Modality.TRANSCRIPT: settings.document_db.collections.transcript_chunks,
        Modality.FRAME: settings.document_db.collections.frame_chunks,
        Modality.AUDIO: settings.document_db.collections.audio_chunks,
        Modality.VIDEO: settings.document_db.collections.video_chunks,
    }
    chunk_counts: dict[str, int] = {}
    for modality, collection in chunk_collection_map.items():
        chunk_counts[modality.value] = await document_db.count(collection, {})

    latest_videos = await storage.list_videos(limit=1)

    return AdminOverviewResponse(
        total_videos=sum(processing_state_counts.values()),
        videos_by_status=status_counts,
        videos_by_processing_state=processing_state_counts,
        total_chunks=sum(chunk_counts.values()),
        chunks_by_modality=chunk_counts,
        latest_ingestion_at=latest_videos[0].created_at if latest_videos else None,
    )


@router.get(
    "/admin/videos/{video_id}",
    response_model=AdminVideoDetailResponse,
    summary="Get admin video detail",
    description="Return detailed metadata and original media links for a video.",
)
async def get_admin_video_detail(
    video_id: str,
    storage: StorageServiceDep,
) -> AdminVideoDetailResponse:
    """Get detailed metadata for a single indexed video."""
    video = await storage.get_video_metadata(video_id)
    if video is None:
        raise APIError(
            code="VIDEO_NOT_FOUND",
            message=f"Video with ID '{video_id}' was not found",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"video_id": video_id},
        )

    return AdminVideoDetailResponse(
        id=video.id,
        youtube_id=video.youtube_id,
        youtube_url=video.youtube_url,
        title=video.title,
        description=video.description,
        duration_seconds=video.duration_seconds,
        duration_display=video.duration_formatted,
        status=_to_ingestion_status(video.status),
        processing_state=video.status,
        chunk_counts=_video_chunk_counts(video),
        total_chunks=video.total_chunk_count,
        created_at=video.created_at,
        updated_at=video.updated_at,
        upload_date=video.upload_date,
        channel_name=video.channel_name,
        channel_id=video.channel_id,
        thumbnail_url=video.thumbnail_url,
        language=video.language,
        error_message=(
            video.error_message if video.status == VideoStatus.FAILED else None
        ),
        artifacts=await _build_video_artifacts(storage, video),
    )


@router.get(
    "/admin/videos/{video_id}/chunks",
    response_model=AdminChunksResponse,
    summary="List indexed chunks for a video",
    description="Inspect stored transcript, frame, audio, and video chunks.",
)
async def get_admin_video_chunks(
    video_id: str,
    storage: StorageServiceDep,
    modality: Annotated[
        Modality | None,
        Query(description="Optional modality filter"),
    ] = None,
    offset: Annotated[
        int,
        Query(ge=0, description="Number of chunks to skip"),
    ] = 0,
    limit: Annotated[
        int,
        Query(ge=1, le=500, description="Number of chunks to return"),
    ] = 120,
) -> AdminChunksResponse:
    """List indexed chunks for the selected video."""
    video = await storage.get_video_metadata(video_id)
    if video is None:
        raise APIError(
            code="VIDEO_NOT_FOUND",
            message=f"Video with ID '{video_id}' was not found",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"video_id": video_id},
        )

    chunks = await storage.get_chunks_for_video(video_id, modality)
    ordered_chunks = sorted(
        chunks, key=lambda chunk: (chunk.start_time, chunk.modality)
    )
    paged_chunks = ordered_chunks[offset : offset + limit]

    return AdminChunksResponse(
        video_id=video_id,
        modality=modality,
        chunk_counts=_video_chunk_counts(video),
        pagination=ChunkPaginationResponse(
            offset=offset,
            limit=limit,
            total_items=len(ordered_chunks),
        ),
        chunks=[
            await _build_chunk_response(storage, video, chunk) for chunk in paged_chunks
        ],
    )


@router.get(
    "/admin/youtube-auth",
    response_model=YouTubeAuthStatus,
    summary="Get YouTube auth status",
    description="Inspect the managed yt-dlp cookie state used for downloads.",
)
async def get_youtube_auth_status(
    service: YouTubeAuthServiceDep,
) -> YouTubeAuthStatus:
    """Get the current managed YouTube auth status."""
    return await service.get_status()


@router.put(
    "/admin/youtube-auth/cookie",
    response_model=YouTubeAuthStatus,
    summary="Save managed YouTube cookie",
    description="Persist an encrypted yt-dlp cookies.txt export for downloads.",
)
async def save_youtube_cookie(
    request: UpdateYouTubeCookieRequest,
    service: YouTubeAuthServiceDep,
) -> YouTubeAuthStatus:
    """Save an encrypted managed yt-dlp cookie."""
    try:
        return await service.save_cookie(
            cookie_text=request.cookie_text,
            source_label=request.source_label,
        )
    except ValueError as exc:
        raise APIError(
            code="INVALID_YOUTUBE_COOKIE",
            message=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc
    except RuntimeError as exc:
        raise APIError(
            code="YOUTUBE_COOKIE_UNAVAILABLE",
            message=str(exc),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc


@router.delete(
    "/admin/youtube-auth/cookie",
    response_model=YouTubeAuthStatus,
    summary="Clear managed YouTube cookie",
    description=(
        "Delete the managed encrypted cookie and disable authenticated downloads."
    ),
)
async def clear_youtube_cookie(
    service: YouTubeAuthServiceDep,
) -> YouTubeAuthStatus:
    """Clear the managed yt-dlp cookie."""
    return await service.clear_cookie()


@router.post(
    "/admin/youtube-auth/download-test",
    response_model=YouTubeDownloadTestResult,
    summary="Run YouTube download diagnostic",
    description=(
        "Attempt an ephemeral audio-only yt-dlp download using the currently "
        "active managed cookie state. Nothing is indexed or persisted."
    ),
)
async def run_youtube_download_test(
    request: YouTubeDownloadTestRequest,
    service: YouTubeAuthServiceDep,
) -> YouTubeDownloadTestResult:
    """Run an ephemeral yt-dlp download diagnostic."""
    try:
        return await service.test_download(youtube_url=request.youtube_url)
    except ValueError as exc:
        raise APIError(
            code="INVALID_YOUTUBE_URL",
            message=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc
    except VideoNotFoundError as exc:
        raise APIError(
            code="YOUTUBE_VIDEO_NOT_FOUND",
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        ) from exc
    except DownloadError as exc:
        raise APIError(
            code=exc.code,
            message=str(exc),
            status_code=exc.status_code,
            details=exc.details,
        ) from exc


@router.post(
    "/admin/youtube-auth/download-audio",
    response_class=FileResponse,
    summary="Download YouTube audio in the browser",
    description=(
        "Fetch audio-only media with the current managed cookie state, return it "
        "as a browser download, and delete the temporary artifact after the "
        "response completes."
    ),
)
async def download_youtube_audio(
    request: BrowserAudioDownloadRequest,
    service: YouTubeAuthServiceDep,
) -> FileResponse:
    """Prepare an ephemeral audio file and return it as an attachment."""
    try:
        prepared_download = await service.prepare_audio_download(
            youtube_url=request.youtube_url,
            preset=request.preset,
        )
    except ValueError as exc:
        raise APIError(
            code="INVALID_YOUTUBE_URL",
            message=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc
    except VideoNotFoundError as exc:
        raise APIError(
            code="YOUTUBE_VIDEO_NOT_FOUND",
            message=str(exc),
            status_code=status.HTTP_404_NOT_FOUND,
        ) from exc
    except DownloadError as exc:
        raise APIError(
            code=exc.code,
            message=str(exc),
            status_code=exc.status_code,
            details=exc.details,
        ) from exc

    return FileResponse(
        path=prepared_download.file_path,
        media_type=_audio_media_type(prepared_download.audio_format),
        filename=_build_audio_download_filename(
            prepared_download.title,
            prepared_download.youtube_id,
            prepared_download.audio_format,
        ),
        headers={"X-YouTube-Auth-Mode": prepared_download.auth_mode.value},
        background=BackgroundTask(
            _cleanup_prepared_audio_download,
            str(prepared_download.cleanup_dir),
        ),
    )


def _to_ingestion_status(video_status: VideoStatus) -> IngestionStatus:
    """Map internal processing states to user-facing ingestion statuses."""
    if video_status == VideoStatus.READY:
        return IngestionStatus.COMPLETED
    if video_status == VideoStatus.FAILED:
        return IngestionStatus.FAILED
    if video_status == VideoStatus.PENDING:
        return IngestionStatus.PENDING
    return IngestionStatus.IN_PROGRESS


def _video_chunk_counts(video: VideoMetadata) -> dict[str, int]:
    """Serialize chunk counts from video metadata."""
    return {
        Modality.TRANSCRIPT.value: video.transcript_chunk_count,
        Modality.FRAME.value: video.frame_chunk_count,
        Modality.AUDIO.value: video.audio_chunk_count,
        Modality.VIDEO.value: video.video_chunk_count,
    }


async def _build_video_artifacts(
    storage: VideoStorageService,
    video: VideoMetadata,
) -> list[AdminArtifactResponse]:
    """Build direct links to stored original media."""
    artifacts: list[AdminArtifactResponse] = []
    videos_bucket = storage._videos_bucket

    if video.blob_path_video:
        artifacts.append(
            AdminArtifactResponse(
                type="original_video",
                label="Original video",
                bucket=videos_bucket,
                path=video.blob_path_video,
                url=await _safe_presigned_url(
                    storage, videos_bucket, video.blob_path_video
                ),
            )
        )

    if video.blob_path_audio:
        artifacts.append(
            AdminArtifactResponse(
                type="original_audio",
                label="Original audio",
                bucket=videos_bucket,
                path=video.blob_path_audio,
                url=await _safe_presigned_url(
                    storage, videos_bucket, video.blob_path_audio
                ),
            )
        )

    artifacts.append(
        AdminArtifactResponse(
            type="youtube_thumbnail",
            label="YouTube thumbnail",
            url=video.thumbnail_url,
        )
    )
    return artifacts


async def _build_chunk_response(
    storage: VideoStorageService,
    video: VideoMetadata,
    chunk: BaseChunk,
) -> AdminChunkResponse:
    """Build a serialized chunk entry for the admin UI."""
    return AdminChunkResponse(
        id=chunk.id,
        modality=chunk.modality,
        start_time=chunk.start_time,
        end_time=chunk.end_time,
        duration_seconds=chunk.duration_seconds,
        timestamp=chunk.format_time_range(),
        youtube_url=f"{video.youtube_url}&t={int(chunk.start_time)}",
        preview=_chunk_preview(chunk),
        created_at=chunk.created_at,
        metadata=_chunk_metadata(chunk),
        artifacts=await _chunk_artifacts(storage, chunk),
    )


def _chunk_preview(chunk: BaseChunk) -> str:
    """Return a compact preview string for the chunk."""
    if isinstance(chunk, TranscriptChunk):
        return _truncate(chunk.text)
    if isinstance(chunk, FrameChunk):
        return chunk.description or f"Frame {chunk.frame_number}"
    if isinstance(chunk, AudioChunk):
        return f"Audio chunk ({chunk.format.upper()})"
    if isinstance(chunk, VideoChunk):
        return chunk.description or f"Video chunk ({chunk.format.upper()})"
    return chunk.id


def _chunk_metadata(chunk: BaseChunk) -> dict[str, str | int | float | bool | None]:
    """Return modality-specific metadata for a chunk."""
    if isinstance(chunk, TranscriptChunk):
        return {
            "language": chunk.language,
            "confidence": round(chunk.confidence, 3),
            "word_count": chunk.word_count,
        }
    if isinstance(chunk, FrameChunk):
        return {
            "frame_number": chunk.frame_number,
            "width": chunk.width,
            "height": chunk.height,
            "resolution": chunk.resolution,
            "description_present": chunk.description is not None,
        }
    if isinstance(chunk, AudioChunk):
        return {
            "format": chunk.format,
            "sample_rate": chunk.sample_rate,
            "channels": chunk.channels,
            "stereo": chunk.is_stereo,
        }
    if isinstance(chunk, VideoChunk):
        return {
            "format": chunk.format,
            "width": chunk.width,
            "height": chunk.height,
            "resolution": chunk.resolution,
            "fps": round(chunk.fps, 2),
            "size_mb": round(chunk.size_mb, 2),
            "has_audio": chunk.has_audio,
        }
    return {}


async def _chunk_artifacts(
    storage: VideoStorageService,
    chunk: BaseChunk,
) -> list[AdminArtifactResponse]:
    """Build artifact links and inline content for a chunk."""
    artifacts: list[AdminArtifactResponse] = []

    if isinstance(chunk, TranscriptChunk):
        artifacts.append(
            AdminArtifactResponse(
                type="transcript_text",
                label="Transcript text",
                content=chunk.text,
            )
        )
        if chunk.blob_path:
            bucket = storage._chunks_bucket
            artifacts.append(
                AdminArtifactResponse(
                    type="transcript_json",
                    label="Transcript JSON",
                    bucket=bucket,
                    path=chunk.blob_path,
                    url=await _safe_presigned_url(storage, bucket, chunk.blob_path),
                )
            )
        return artifacts

    if isinstance(chunk, FrameChunk):
        bucket = storage._frames_bucket
        artifacts.append(
            AdminArtifactResponse(
                type="frame_image",
                label="Frame image",
                bucket=bucket,
                path=chunk.blob_path,
                url=await _safe_presigned_url(storage, bucket, chunk.blob_path),
            )
        )
        artifacts.append(
            AdminArtifactResponse(
                type="thumbnail",
                label="Thumbnail",
                bucket=bucket,
                path=chunk.thumbnail_path,
                url=await _safe_presigned_url(storage, bucket, chunk.thumbnail_path),
            )
        )
        return artifacts

    if isinstance(chunk, AudioChunk):
        bucket = storage._chunks_bucket
        artifacts.append(
            AdminArtifactResponse(
                type="audio_clip",
                label="Audio clip",
                bucket=bucket,
                path=chunk.blob_path,
                url=await _safe_presigned_url(storage, bucket, chunk.blob_path),
            )
        )
        return artifacts

    if isinstance(chunk, VideoChunk):
        bucket = storage._chunks_bucket
        artifacts.append(
            AdminArtifactResponse(
                type="video_clip",
                label="Video clip",
                bucket=bucket,
                path=chunk.blob_path,
                url=await _safe_presigned_url(storage, bucket, chunk.blob_path),
            )
        )
        if chunk.thumbnail_path:
            artifacts.append(
                AdminArtifactResponse(
                    type="thumbnail",
                    label="Thumbnail",
                    bucket=bucket,
                    path=chunk.thumbnail_path,
                    url=await _safe_presigned_url(
                        storage,
                        bucket,
                        chunk.thumbnail_path,
                    ),
                )
            )
        return artifacts

    return artifacts


def _build_audio_download_filename(
    title: str,
    youtube_id: str,
    audio_format: str,
) -> str:
    """Create a predictable ASCII filename for browser downloads."""
    slug = _DOWNLOAD_FILENAME_PATTERN.sub("-", title).strip("-").lower()
    stem = slug[:80] or youtube_id
    return f"{stem}-{youtube_id}.{audio_format}"


def _audio_media_type(audio_format: str) -> str:
    """Map response media types for the supported audio presets."""
    if audio_format == "m4a":
        return "audio/mp4"
    if audio_format == "opus":
        return "audio/ogg"
    return "audio/mpeg"


def _cleanup_prepared_audio_download(cleanup_dir: str) -> None:
    """Delete the temporary directory used for a browser audio download."""
    from shutil import rmtree

    rmtree(cleanup_dir, ignore_errors=True)


async def _safe_presigned_url(
    storage: VideoStorageService,
    bucket: str,
    path: str,
) -> str | None:
    """Best-effort presigned URL generation."""
    try:
        return await storage.get_presigned_url(bucket, path)
    except Exception:
        return None


def _truncate(value: str, limit: int = 260) -> str:
    """Truncate long preview text for UI use."""
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"
