"""DTOs for the agent playground chat interface."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class AgentChatMessageInput(BaseModel):
    """Single chat message exchanged with the agent playground."""

    role: Literal["user", "assistant"] = Field(description="Chat message role")
    content: str = Field(
        min_length=1,
        max_length=8000,
        description="Message content",
    )


class AgentToolTrace(BaseModel):
    """Trace entry for a tool used by the playground agent."""

    tool_name: str = Field(description="Agent-facing tool name")
    mcp_tool_name: str = Field(description="Underlying MCP tool name")
    arguments: dict[str, Any] = Field(
        default_factory=dict,
        description="Arguments sent to the tool",
    )
    result_preview: str = Field(description="Truncated result preview")


class AgentChatResult(BaseModel):
    """Agent response payload for the playground UI."""

    reply: str = Field(description="Assistant response text")
    response_id: str | None = Field(
        default=None,
        description="Underlying model response identifier",
    )
    tool_traces: list[AgentToolTrace] = Field(
        default_factory=list,
        description="Tools used during the run",
    )
