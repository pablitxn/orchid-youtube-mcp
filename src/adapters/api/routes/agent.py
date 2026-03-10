"""Agent playground endpoints."""

from fastapi import APIRouter, status
from orchid_commons import APIError
from pydantic import BaseModel, Field

from src.adapters.dependencies import AgentPlaygroundServiceDep
from src.application.dtos.agent import (
    AgentChatMessageInput,
    AgentToolTrace,
)

router = APIRouter()


class AgentChatRequest(BaseModel):
    """Request model for the selected-video agent playground."""

    messages: list[AgentChatMessageInput] = Field(
        min_length=1,
        max_length=24,
        description="Ordered chat history including the latest user message",
    )


class AgentChatResponse(BaseModel):
    """Response model for the selected-video agent playground."""

    reply: str = Field(description="Assistant reply")
    response_id: str | None = Field(
        default=None,
        description="Provider response identifier",
    )
    tool_traces: list[AgentToolTrace] = Field(
        default_factory=list,
        description="Tool calls performed during the run",
    )


@router.post(
    "/agent/videos/{video_id}/chat",
    response_model=AgentChatResponse,
    summary="Chat with the selected video agent",
    description=(
        "Run the Microsoft Agent Framework playground agent against the "
        "selected video using the same MCP server."
    ),
)
async def chat_with_video_agent(
    video_id: str,
    request: AgentChatRequest,
    service: AgentPlaygroundServiceDep,
) -> AgentChatResponse:
    """Run a grounded chat turn for the selected video."""
    try:
        result = await service.chat(video_id, request.messages)
        return AgentChatResponse(
            reply=result.reply,
            response_id=result.response_id,
            tool_traces=result.tool_traces,
        )
    except ValueError as exc:
        error_message = str(exc)
        if "not found" in error_message.lower():
            raise APIError(
                code="VIDEO_NOT_FOUND",
                message=f"Video with ID '{video_id}' was not found",
                status_code=status.HTTP_404_NOT_FOUND,
                details={"video_id": video_id},
            ) from exc
        raise APIError(
            code="AGENT_CHAT_ERROR",
            message=error_message,
            status_code=status.HTTP_400_BAD_REQUEST,
        ) from exc
    except RuntimeError as exc:
        raise APIError(
            code="AGENT_CHAT_UNAVAILABLE",
            message=str(exc),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
