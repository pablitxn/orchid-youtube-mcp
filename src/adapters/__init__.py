"""API layer - REST and MCP endpoints."""

from src.adapters.main import app, create_app
from src.adapters.mcp import create_mcp_server, run_mcp_server

__all__ = [
    "app",
    "create_app",
    "create_mcp_server",
    "run_mcp_server",
]
