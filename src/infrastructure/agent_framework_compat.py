"""Compatibility helpers for Microsoft Agent Framework preview builds."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentFrameworkBindings:
    """Resolved Agent Framework objects loaded at runtime."""

    Agent: Any
    MCPStdioTool: Any
    Message: Any
    OpenAIResponsesClient: Any
    tool: Any


def load_agent_framework_bindings() -> AgentFrameworkBindings:
    """Load Agent Framework after applying MCP transport compatibility shims.

    Agent Framework `1.0.0rc3` imports `streamable_http_client` from the `mcp`
    package, while newer MCP builds expose that transport as
    `streamablehttp_client`. We alias the new name to the old one before
    importing Agent Framework so the preview package can initialize cleanly.
    """
    from mcp.client import streamable_http

    replacement = getattr(streamable_http, "streamablehttp_client", None)
    if not hasattr(streamable_http, "streamable_http_client") and callable(replacement):
        streamable_http_any: Any = streamable_http
        streamable_http_any.streamable_http_client = replacement

    from agent_framework import Agent, MCPStdioTool, Message, tool
    from agent_framework.openai import OpenAIResponsesClient

    return AgentFrameworkBindings(
        Agent=Agent,
        MCPStdioTool=MCPStdioTool,
        Message=Message,
        OpenAIResponsesClient=OpenAIResponsesClient,
        tool=tool,
    )
