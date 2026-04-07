"""Audio download endpoints."""

from fastapi import APIRouter, status

from src.adapters.api.errors import APIError
from src.adapters.dependencies import AudioDownloadServiceDep
from src.application.dtos.audio_download import (
    AudioDownloadBatchRequest,
    AudioDownloadBatchResponse,
)

router = APIRouter()


@router.post(
    "/audio/downloads/batch",
    response_model=AudioDownloadBatchResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Queue a batch audio download job",
    description=(
        "Queue a list of YouTube URLs for audio-only download. "
        "The server processes the list in the background with a maximum "
        "concurrency of 3."
    ),
)
async def queue_audio_download_batch(
    request: AudioDownloadBatchRequest,
    service: AudioDownloadServiceDep,
) -> AudioDownloadBatchResponse:
    """Queue a new audio batch download job."""
    return await service.submit_batch(request)


@router.get(
    "/audio/downloads/batch/{job_id}",
    response_model=AudioDownloadBatchResponse,
    summary="Get audio batch download status",
    description="Retrieve the current state of an audio-only batch download job.",
)
async def get_audio_download_batch(
    job_id: str,
    service: AudioDownloadServiceDep,
) -> AudioDownloadBatchResponse:
    """Get the current status snapshot for an audio batch job."""
    result = await service.get_batch(job_id)
    if result is None:
        raise APIError(
            code="AUDIO_BATCH_NOT_FOUND",
            message=f"Audio batch job '{job_id}' was not found",
            status_code=status.HTTP_404_NOT_FOUND,
            details={"job_id": job_id},
        )
    return result
