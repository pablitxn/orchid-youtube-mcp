"""MCP server implementation."""

from src.api.mcp.server import create_mcp_server, run_mcp_server
from src.api.mcp.tools import (
    delete_video_tool,
    get_ingestion_status_tool,
    get_sources_tool,
    ingest_video_tool,
    list_videos_tool,
    query_video_tool,
)

__all__ = [
    "create_mcp_server",
    "run_mcp_server",
    "delete_video_tool",
    "get_ingestion_status_tool",
    "get_sources_tool",
    "ingest_video_tool",
    "list_videos_tool",
    "query_video_tool",
]
