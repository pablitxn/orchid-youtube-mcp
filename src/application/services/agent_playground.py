"""Agent playground service backed by Microsoft Agent Framework."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from src.application.dtos.agent import (
    AgentChatMessageInput,
    AgentChatResult,
    AgentToolTrace,
)
from src.infrastructure.agent_framework_compat import load_agent_framework_bindings
from src.infrastructure.telemetry import get_logger

if TYPE_CHECKING:
    from src.application.services.storage import VideoStorageService
    from src.domain.models.video import VideoMetadata
    from src.infrastructure.settings.models import Settings


class VideoAgentPlaygroundService:
    """Chat playground that uses the app's own MCP server through stdio."""

    def __init__(
        self,
        *,
        settings: Settings,
        storage_service: VideoStorageService,
    ) -> None:
        self._settings = settings
        self._storage = storage_service
        self._logger = get_logger(__name__)
        self._project_root = Path(__file__).resolve().parents[3]

    async def chat(
        self,
        video_id: str,
        messages: list[AgentChatMessageInput],
    ) -> AgentChatResult:
        """Run the selected-video agent against the existing MCP server."""
        if not messages:
            raise ValueError("At least one chat message is required")

        video = await self._storage.get_video_metadata(video_id)
        if video is None:
            raise ValueError(f"Video not found: {video_id}")

        if self._settings.llm.provider not in {"openai", "azure_openai"}:
            raise RuntimeError(
                "Agent playground currently requires "
                "llm.provider=openai or azure_openai"
            )

        if not self._settings.llm.api_key:
            raise RuntimeError("LLM API key is not configured for the agent playground")

        bindings = load_agent_framework_bindings()
        client = bindings.OpenAIResponsesClient(
            model_id=self._settings.llm.deployment or self._settings.llm.model,
            api_key=self._settings.llm.api_key,
            base_url=self._settings.llm.endpoint,
        )
        tool_traces: list[AgentToolTrace] = []

        mcp_tool = bindings.MCPStdioTool(
            name="youtube-mcp",
            description="Local YouTube MCP server for indexed video operations.",
            command=sys.executable,
            args=[
                "-c",
                (
                    "import asyncio; "
                    "from src.adapters.mcp import run_mcp_server; "
                    "asyncio.run(run_mcp_server())"
                ),
            ],
            env=self._mcp_environment(),
            cwd=str(self._project_root),
            load_tools=True,
            load_prompts=False,
            request_timeout=self._settings.llm.timeout_seconds,
        )

        async with mcp_tool:

            @bindings.tool(
                name="query_selected_video",
                description=(
                    "Search only the currently selected indexed video and return "
                    "grounded JSON with answer, reasoning, confidence, and citations."
                ),
            )
            async def query_selected_video(
                query: str,
                modalities: list[str] | None = None,
                max_citations: int = 5,
                include_reasoning: bool = True,
            ) -> str:
                payload = {
                    "video_id": video.id,
                    "query": query,
                    "modalities": modalities or ["transcript", "frame"],
                    "max_citations": max_citations,
                    "include_reasoning": include_reasoning,
                }
                result = await mcp_tool.call_tool("query_video", **payload)
                result_text = str(result)
                tool_traces.append(
                    AgentToolTrace(
                        tool_name="query_selected_video",
                        mcp_tool_name="query_video",
                        arguments=payload,
                        result_preview=_truncate(result_text),
                    )
                )
                return result_text

            @bindings.tool(
                name="get_selected_sources",
                description=(
                    "Fetch artifacts and source details for citation IDs from the "
                    "currently selected video."
                ),
            )
            async def get_selected_sources(
                citation_ids: list[str],
                include_artifacts: list[str] | None = None,
            ) -> str:
                payload = {
                    "video_id": video.id,
                    "citation_ids": citation_ids,
                    "include_artifacts": include_artifacts
                    or [
                        "transcript_text",
                        "thumbnail",
                        "frame_image",
                        "audio_clip",
                        "video_clip",
                    ],
                }
                result = await mcp_tool.call_tool("get_sources", **payload)
                result_text = str(result)
                tool_traces.append(
                    AgentToolTrace(
                        tool_name="get_selected_sources",
                        mcp_tool_name="get_sources",
                        arguments=payload,
                        result_preview=_truncate(result_text),
                    )
                )
                return result_text

            @bindings.tool(
                name="get_selected_video_status",
                description=(
                    "Get ingestion/indexing status for the currently selected video."
                ),
            )
            async def get_selected_video_status() -> str:
                payload = {"video_id": video.id}
                result = await mcp_tool.call_tool("get_ingestion_status", **payload)
                result_text = str(result)
                tool_traces.append(
                    AgentToolTrace(
                        tool_name="get_selected_video_status",
                        mcp_tool_name="get_ingestion_status",
                        arguments=payload,
                        result_preview=_truncate(result_text),
                    )
                )
                return result_text

            agent = bindings.Agent(
                client=client,
                name="selected-video-playground",
                instructions=self._build_instructions(video),
                tools=[
                    query_selected_video,
                    get_selected_sources,
                    get_selected_video_status,
                ],
            )

            af_messages = [
                bindings.Message(role=item.role, contents=[item.content])
                for item in messages[-24:]
            ]
            response = await agent.run(af_messages)

        reply = response.text.strip() or "No response returned."
        self._logger.info(
            "Agent playground chat completed",
            extra={
                "video_id": video_id,
                "tool_calls": len(tool_traces),
                "response_id": response.response_id,
            },
        )

        return AgentChatResult(
            reply=reply,
            response_id=response.response_id,
            tool_traces=tool_traces,
        )

    def _build_instructions(self, video: VideoMetadata) -> str:
        """Build system instructions for the selected-video chat agent."""
        return (
            "You are a personal video research assistant for a single indexed "
            "YouTube video.\n\n"
            "Selected video:\n"
            f"- Internal ID: {video.id}\n"
            f"- YouTube ID: {video.youtube_id}\n"
            f"- Title: {video.title}\n"
            f"- Channel: {video.channel_name}\n"
            f"- Duration: {video.duration_formatted}\n"
            f"- Processing state: {video.status.value}\n"
            f"- Transcript chunks: {video.transcript_chunk_count}\n"
            f"- Frame chunks: {video.frame_chunk_count}\n"
            f"- Audio chunks: {video.audio_chunk_count}\n"
            f"- Video chunks: {video.video_chunk_count}\n"
            f"- YouTube URL: {video.youtube_url}\n\n"
            "Rules:\n"
            "- This conversation is only about the selected video.\n"
            "- Use the provided tools for any question about the video's "
            "actual content.\n"
            "- Do not invent facts. If evidence is missing, say so plainly.\n"
            "- Prefer transcript+frame search by default.\n"
            "- If the user asks about visuals or what is seen on screen, "
            "include frame modality.\n"
            "- If the user asks for proof, quotes, clips, or screenshots, "
            "call get_selected_sources.\n"
            "- Include timestamps when the tool results provide them.\n"
            "- Keep answers concise and useful."
        )

    def _mcp_environment(self) -> dict[str, str]:
        """Build subprocess environment for the stdio MCP server."""
        environment = dict(os.environ)
        current_pythonpath = environment.get("PYTHONPATH")
        if current_pythonpath:
            environment["PYTHONPATH"] = (
                f"{self._project_root}{os.pathsep}{current_pythonpath}"
            )
        else:
            environment["PYTHONPATH"] = str(self._project_root)
        environment.setdefault("PYTHONUNBUFFERED", "1")
        return environment


def _truncate(value: str, limit: int = 800) -> str:
    """Truncate tool outputs for trace rendering."""
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"
