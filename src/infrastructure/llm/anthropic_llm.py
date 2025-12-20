"""Anthropic implementation of LLM service."""

import base64
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

from anthropic import AsyncAnthropic

from src.commons.telemetry import create_llm_generation, end_llm_generation
from src.infrastructure.llm.base import (
    FunctionCall,
    FunctionDefinition,
    LLMResponse,
    LLMResponseWithTools,
    LLMServiceBase,
    LLMUsage,
    Message,
    MessageRole,
)


class AnthropicLLMService(LLMServiceBase):
    """Anthropic implementation of LLM service.

    Supports Claude 4, Claude 3.5 Sonnet/Haiku, Claude 3 Opus, and other models.
    """

    # Model capabilities - all Claude 3+ models support vision
    _VISION_MODELS: ClassVar[set[str]] = {
        "claude-sonnet-4-20250514",
        "claude-3-7-sonnet-20250219",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet-20240620",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
    }

    # All Claude 3+ models support function calling
    _FUNCTION_CALLING_MODELS: ClassVar[set[str]] = {
        "claude-sonnet-4-20250514",
        "claude-3-7-sonnet-20250219",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet-20240620",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
    }

    # Context windows
    _CONTEXT_WINDOWS: ClassVar[dict[str, int]] = {
        "claude-sonnet-4-20250514": 200000,
        "claude-3-7-sonnet-20250219": 200000,
        "claude-3-5-sonnet-20241022": 200000,
        "claude-3-5-sonnet-20240620": 200000,
        "claude-3-5-haiku-20241022": 200000,
        "claude-3-opus-20240229": 200000,
        "claude-3-sonnet-20240229": 200000,
        "claude-3-haiku-20240307": 200000,
    }

    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-20250514",
        base_url: str | None = None,
        max_retries: int = 2,
    ) -> None:
        """Initialize Anthropic LLM client.

        Args:
            api_key: Anthropic API key.
            model: Default model to use.
            base_url: Optional custom API endpoint.
            max_retries: Maximum number of retries for failed requests.
        """
        self._client = AsyncAnthropic(
            api_key=api_key,
            base_url=base_url,
            max_retries=max_retries,
        )
        self._model = model

    async def generate(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_mode: bool = False,  # noqa: ARG002 - Claude handles JSON via prompting
    ) -> LLMResponse:
        """Generate a completion."""
        use_model = model or self._model
        anthropic_messages, system_prompt = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": use_model,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        # Create Langfuse generation for tracing
        input_for_trace = [
            {"role": m["role"], "content": str(m.get("content", ""))}
            for m in anthropic_messages
        ]
        if system_prompt:
            input_for_trace.insert(0, {"role": "system", "content": system_prompt})

        generation = create_llm_generation(
            name="anthropic_messages",
            model=use_model,
            input_messages=input_for_trace,
            model_parameters={
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            metadata={"provider": "anthropic"},
        )

        try:
            response = await self._client.messages.create(**kwargs)

            # Extract text content
            content = ""
            for block in response.content:
                if block.type == "text":
                    content = block.text
                    break

            result = LLMResponse(
                content=content,
                finish_reason=response.stop_reason or "end_turn",
                usage=LLMUsage(
                    prompt_tokens=response.usage.input_tokens,
                    completion_tokens=response.usage.output_tokens,
                    total_tokens=response.usage.input_tokens
                    + response.usage.output_tokens,
                ),
                model=response.model,
            )

            # End Langfuse generation with success
            end_llm_generation(
                generation=generation,
                output=result.content,
                usage={
                    "prompt_tokens": result.usage.prompt_tokens,
                    "completion_tokens": result.usage.completion_tokens,
                    "total_tokens": result.usage.total_tokens,
                },
                metadata={"finish_reason": result.finish_reason},
            )

            return result

        except Exception as e:
            # End Langfuse generation with error
            end_llm_generation(
                generation=generation,
                output=None,
                level="ERROR",
                status_message=str(e),
            )
            raise

    async def generate_stream(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[str]:
        """Generate a streaming completion."""
        use_model = model or self._model
        anthropic_messages, system_prompt = self._convert_messages(messages)

        kwargs: dict[str, Any] = {
            "model": use_model,
            "messages": anthropic_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        async with self._client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text

    async def generate_with_tools(
        self,
        messages: list[Message],
        functions: list[FunctionDefinition],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponseWithTools:
        """Generate a completion that may call functions."""
        use_model = model or self._model
        anthropic_messages, system_prompt = self._convert_messages(messages)
        tools = self._convert_functions(functions)

        kwargs: dict[str, Any] = {
            "model": use_model,
            "messages": anthropic_messages,
            "tools": tools,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if system_prompt:
            kwargs["system"] = system_prompt

        # Create Langfuse generation for tracing
        input_for_trace = [
            {"role": m["role"], "content": str(m.get("content", ""))}
            for m in anthropic_messages
        ]
        if system_prompt:
            input_for_trace.insert(0, {"role": "system", "content": system_prompt})

        generation = create_llm_generation(
            name="anthropic_messages_with_tools",
            model=use_model,
            input_messages=input_for_trace,
            model_parameters={
                "temperature": temperature,
                "max_tokens": max_tokens,
                "tools": [f.name for f in functions],
            },
            metadata={"provider": "anthropic", "has_tools": True},
        )

        try:
            response = await self._client.messages.create(**kwargs)

            # Extract content and tool calls
            content: str | None = None
            function_calls: list[FunctionCall] = []

            for block in response.content:
                if block.type == "text":
                    content = block.text
                elif block.type == "tool_use":
                    function_calls.append(
                        FunctionCall(
                            name=block.name,
                            arguments=dict(block.input)
                            if isinstance(block.input, dict)
                            else {},
                        )
                    )

            result = LLMResponseWithTools(
                content=content,
                finish_reason=response.stop_reason or "end_turn",
                usage=LLMUsage(
                    prompt_tokens=response.usage.input_tokens,
                    completion_tokens=response.usage.output_tokens,
                    total_tokens=response.usage.input_tokens
                    + response.usage.output_tokens,
                ),
                model=response.model,
                function_calls=function_calls,
            )

            # End Langfuse generation with success
            end_llm_generation(
                generation=generation,
                output={
                    "content": result.content,
                    "function_calls": [
                        {"name": fc.name, "arguments": fc.arguments}
                        for fc in result.function_calls
                    ],
                },
                usage={
                    "prompt_tokens": result.usage.prompt_tokens,
                    "completion_tokens": result.usage.completion_tokens,
                    "total_tokens": result.usage.total_tokens,
                },
                metadata={
                    "finish_reason": result.finish_reason,
                    "tool_calls_count": len(result.function_calls),
                },
            )

            return result

        except Exception as e:
            # End Langfuse generation with error
            end_llm_generation(
                generation=generation,
                output=None,
                level="ERROR",
                status_message=str(e),
            )
            raise

    def _convert_messages(
        self,
        messages: list[Message],
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Convert our Message format to Anthropic format.

        Returns:
            Tuple of (messages list, system prompt or None).
        """
        result: list[dict[str, Any]] = []
        system_prompt: str | None = None

        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                # Anthropic handles system prompts separately
                system_prompt = msg.content
            elif msg.role == MessageRole.ASSISTANT:
                result.append({"role": "assistant", "content": msg.content})
            elif msg.role == MessageRole.USER:
                # Check for multimodal content
                if msg.images or msg.videos:
                    content: list[dict[str, Any]] = []

                    # Add images
                    for image in msg.images or []:
                        image_data = self._prepare_image(image)
                        if image_data:
                            content.append(image_data)

                    # Add text
                    content.append({"type": "text", "text": msg.content})

                    result.append({"role": "user", "content": content})
                else:
                    result.append({"role": "user", "content": msg.content})

        return result, system_prompt

    def _prepare_image(self, image: str) -> dict[str, Any] | None:
        """Prepare image for Anthropic API.

        Args:
            image: URL, file path, or base64 string.

        Returns:
            Anthropic image content block or None.
        """
        if image.startswith("http://") or image.startswith("https://"):
            # URL - Anthropic supports direct URLs
            return {
                "type": "image",
                "source": {
                    "type": "url",
                    "url": image,
                },
            }

        # Check if it's a file path
        path = Path(image)
        if path.exists():
            with path.open("rb") as f:
                b64 = base64.standard_b64encode(f.read()).decode()
                ext = path.suffix.lstrip(".").lower()
                media_type = self._get_media_type(ext)
                return {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": b64,
                    },
                }

        # Assume it's already base64
        # Try to detect media type from data URI or default to jpeg
        if image.startswith("data:"):
            # Parse data URI
            parts = image.split(",", 1)
            if len(parts) == 2:
                media_type = parts[0].split(":")[1].split(";")[0]
                return {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": parts[1],
                    },
                }

        # Plain base64, assume jpeg
        return {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": image,
            },
        }

    @staticmethod
    def _get_media_type(ext: str) -> str:
        """Get media type from file extension."""
        media_types = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
        }
        return media_types.get(ext, "image/jpeg")

    def _convert_functions(
        self,
        functions: list[FunctionDefinition],
    ) -> list[dict[str, Any]]:
        """Convert our FunctionDefinition to Anthropic tool format."""
        tools: list[dict[str, Any]] = []

        for func in functions:
            properties: dict[str, Any] = {}
            required: list[str] = []

            for param in func.parameters:
                prop: dict[str, Any] = {
                    "type": param.type,
                    "description": param.description,
                }
                if param.enum:
                    prop["enum"] = param.enum

                properties[param.name] = prop
                if param.required:
                    required.append(param.name)

            tools.append(
                {
                    "name": func.name,
                    "description": func.description,
                    "input_schema": {
                        "type": "object",
                        "properties": properties,
                        "required": required,
                    },
                }
            )

        return tools

    @property
    def supports_vision(self) -> bool:
        """Whether this model supports image input."""
        return self._model in self._VISION_MODELS

    @property
    def supports_video(self) -> bool:
        """Whether this model supports video input."""
        return False  # Claude doesn't support video directly yet

    @property
    def supports_function_calling(self) -> bool:
        """Whether this model supports function/tool calling."""
        return self._model in self._FUNCTION_CALLING_MODELS

    @property
    def supports_json_mode(self) -> bool:
        """Whether this model supports JSON output mode."""
        # Claude doesn't have a native JSON mode, but handles JSON well via prompting
        return False

    @property
    def context_window(self) -> int:
        """Maximum context window in tokens."""
        return self._CONTEXT_WINDOWS.get(self._model, 200000)

    @property
    def default_model(self) -> str:
        """Default model identifier."""
        return self._model
