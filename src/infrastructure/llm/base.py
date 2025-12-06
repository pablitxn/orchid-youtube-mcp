"""Abstract base class for LLM services."""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageRole(str, Enum):
    """Role of a message in the conversation."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass
class Message:
    """A message in the conversation."""

    role: MessageRole
    content: str
    images: list[str] | None = None  # Base64 or URLs for vision models
    videos: list[str] | None = None  # Base64 or URLs for video-capable models


@dataclass
class LLMUsage:
    """Token usage statistics."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass
class LLMResponse:
    """Response from LLM generation."""

    content: str
    finish_reason: str
    usage: LLMUsage
    model: str


@dataclass
class FunctionParameter:
    """Parameter definition for function calling."""

    name: str
    type: str
    description: str
    required: bool = True
    enum: list[str] | None = None


@dataclass
class FunctionDefinition:
    """Function definition for tool use."""

    name: str
    description: str
    parameters: list[FunctionParameter] = field(default_factory=list)


@dataclass
class FunctionCall:
    """A function call from the LLM."""

    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponseWithTools:
    """Response that may include function calls."""

    content: str | None
    finish_reason: str
    usage: LLMUsage
    model: str
    function_calls: list[FunctionCall] = field(default_factory=list)


class LLMServiceBase(ABC):
    """Abstract base class for LLM services.

    Implementations should handle:
    - OpenAI (GPT-4o, GPT-4-turbo)
    - Anthropic (Claude 3.5 Sonnet)
    - Google (Gemini 1.5 Pro/Flash)
    - Azure OpenAI
    """

    @abstractmethod
    async def generate(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Generate a completion.

        Args:
            messages: List of conversation messages.
            model: Optional model override.
            temperature: Sampling temperature (0.0-2.0).
            max_tokens: Maximum tokens to generate.
            json_mode: Whether to force JSON output.

        Returns:
            LLM response with content and usage.
        """

    @abstractmethod
    async def generate_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Generate a streaming completion.

        Args:
            messages: List of conversation messages.
            model: Optional model override.
            temperature: Sampling temperature (0.0-2.0).
            max_tokens: Maximum tokens to generate.

        Yields:
            Token strings as they are generated.
        """
        # Make this a generator
        yield  # type: ignore[misc]

    @abstractmethod
    async def generate_with_tools(
        self,
        messages: list[Message],
        functions: list[FunctionDefinition],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponseWithTools:
        """Generate a completion that may call functions.

        Args:
            messages: List of conversation messages.
            functions: Available functions/tools.
            model: Optional model override.
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            Response that may include function calls.
        """

    @property
    @abstractmethod
    def supports_vision(self) -> bool:
        """Whether this model supports image input.

        Returns:
            True if images can be included in messages.
        """

    @property
    @abstractmethod
    def supports_video(self) -> bool:
        """Whether this model supports video input.

        Returns:
            True if videos can be included in messages.
        """

    @property
    @abstractmethod
    def supports_function_calling(self) -> bool:
        """Whether this model supports function/tool calling.

        Returns:
            True if function calling is supported.
        """

    @property
    @abstractmethod
    def supports_json_mode(self) -> bool:
        """Whether this model supports JSON output mode.

        Returns:
            True if JSON mode is supported.
        """

    @property
    @abstractmethod
    def context_window(self) -> int:
        """Maximum context window in tokens.

        Returns:
            Maximum token count for input + output.
        """

    @property
    @abstractmethod
    def default_model(self) -> str:
        """Default model identifier.

        Returns:
            Model identifier string.
        """
