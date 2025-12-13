"""MCP Server implementation for YouTube RAG tools."""

from collections.abc import Sequence
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    EmbeddedResource,
    ImageContent,
    TextContent,
    Tool,
)

from src.api.mcp.tools import (
    delete_video_tool,
    get_ingestion_status_tool,
    get_sources_tool,
    ingest_video_tool,
    list_videos_tool,
    query_video_tool,
)
from src.commons.settings.loader import get_settings
from src.commons.telemetry.logger import get_logger
from src.infrastructure.factory import get_factory

logger = get_logger(__name__)


def create_mcp_server() -> Server:
    """Create and configure the MCP server.

    Returns:
        Configured MCP server instance.
    """
    server = Server("youtube-rag-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """List all available tools."""
        return [
            Tool(
                name="ingest_video",
                description=(
                    "Download and index a YouTube video for semantic search. "
                    "Extracts transcript, frames, and creates embeddings."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "youtube_url": {
                            "type": "string",
                            "description": "Full YouTube URL",
                        },
                        "extract_frames": {
                            "type": "boolean",
                            "default": True,
                            "description": "Extract video frames",
                        },
                        "extract_audio_chunks": {
                            "type": "boolean",
                            "default": True,
                            "description": "Create separate audio chunks",
                        },
                        "extract_video_chunks": {
                            "type": "boolean",
                            "default": False,
                            "description": "Create video segment chunks",
                        },
                        "language_hint": {
                            "type": "string",
                            "description": "Language (ISO 639-1) for transcription",
                        },
                    },
                    "required": ["youtube_url"],
                },
            ),
            Tool(
                name="get_ingestion_status",
                description="Get the processing status of a video ingestion job.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "video_id": {
                            "type": "string",
                            "description": "Video ID from ingest_video",
                        },
                    },
                    "required": ["video_id"],
                },
            ),
            Tool(
                name="query_video",
                description=(
                    "Query video content using natural language. "
                    "Returns answer with timestamp citations."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "video_id": {
                            "type": "string",
                            "description": "Video ID to query",
                        },
                        "query": {
                            "type": "string",
                            "description": "Question about video content",
                        },
                        "modalities": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": ["transcript", "frame", "audio", "video"],
                            },
                            "default": ["transcript", "frame"],
                            "description": "Modalities to search",
                        },
                        "max_citations": {
                            "type": "integer",
                            "default": 5,
                            "minimum": 1,
                            "maximum": 20,
                            "description": "Max citations to return",
                        },
                    },
                    "required": ["video_id", "query"],
                },
            ),
            Tool(
                name="get_sources",
                description=(
                    "Get source artifacts (frames, audio, video) for citations."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "video_id": {
                            "type": "string",
                            "description": "Video ID",
                        },
                        "citation_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Citation IDs to retrieve",
                        },
                        "include_artifacts": {
                            "type": "array",
                            "items": {
                                "type": "string",
                                "enum": [
                                    "transcript_text",
                                    "frame_image",
                                    "audio_clip",
                                    "video_segment",
                                    "thumbnail",
                                ],
                            },
                            "default": ["transcript_text", "thumbnail"],
                            "description": "Artifact types to include",
                        },
                    },
                    "required": ["video_id", "citation_ids"],
                },
            ),
            Tool(
                name="list_videos",
                description="List indexed videos with optional filtering.",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["ready", "processing", "failed", "pending"],
                            "description": "Filter by processing status",
                        },
                        "page": {
                            "type": "integer",
                            "default": 1,
                            "minimum": 1,
                            "description": "Page number",
                        },
                        "page_size": {
                            "type": "integer",
                            "default": 20,
                            "minimum": 1,
                            "maximum": 100,
                            "description": "Items per page",
                        },
                    },
                },
            ),
            Tool(
                name="delete_video",
                description=(
                    "Delete an indexed video and all its associated data "
                    "(chunks, embeddings, artifacts)."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "video_id": {
                            "type": "string",
                            "description": "The video ID to delete",
                        },
                        "confirm": {
                            "type": "boolean",
                            "description": "Must be true to confirm deletion",
                        },
                    },
                    "required": ["video_id", "confirm"],
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(
        name: str,
        arguments: dict[str, Any],
    ) -> Sequence[TextContent | ImageContent | EmbeddedResource]:
        """Handle tool calls."""
        settings = get_settings()
        factory = get_factory(settings)

        try:
            if name == "ingest_video":
                result = await ingest_video_tool(factory, settings, arguments)
            elif name == "get_ingestion_status":
                result = await get_ingestion_status_tool(factory, settings, arguments)
            elif name == "query_video":
                result = await query_video_tool(factory, settings, arguments)
            elif name == "get_sources":
                result = await get_sources_tool(factory, settings, arguments)
            elif name == "list_videos":
                result = await list_videos_tool(factory, settings, arguments)
            elif name == "delete_video":
                result = await delete_video_tool(factory, settings, arguments)
            else:
                result = {"error": f"Unknown tool: {name}"}

            import json

            return [TextContent(type="text", text=json.dumps(result, default=str))]

        except Exception as e:
            logger.exception(f"Error calling tool {name}: {e}")
            import json

            return [
                TextContent(
                    type="text",
                    text=json.dumps({"error": str(e), "tool": name}),
                )
            ]

    return server


async def run_mcp_server() -> None:
    """Run the MCP server using stdio transport."""
    server = create_mcp_server()
    logger.info("Starting MCP server...")

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )
