"""OpenAI implementation of LLM service."""

import base64
import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, ClassVar

from openai import AsyncOpenAI
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)

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


class OpenAILLMService(LLMServiceBase):
    """OpenAI implementation of LLM service.

    Supports GPT-4, GPT-4 Turbo, GPT-4o, and GPT-3.5 Turbo models.
    """

    # Model capabilities
    _VISION_MODELS: ClassVar[set[str]] = {
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4-vision-preview",
    }
    _FUNCTION_CALLING_MODELS: ClassVar[set[str]] = {
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
    }

    # Context windows
    _CONTEXT_WINDOWS: ClassVar[dict[str, int]] = {
        "gpt-4o": 128000,
        "gpt-4o-mini": 128000,
        "gpt-4-turbo": 128000,
        "gpt-4": 8192,
        "gpt-3.5-turbo": 16385,
    }

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
        organization: str | None = None,
    ) -> None:
        """Initialize OpenAI LLM client.

        Args:
            api_key: OpenAI API key.
            model: Default model to use.
            base_url: Optional custom API endpoint.
            organization: Optional organization ID.
        """
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            organization=organization,
        )
        self._model = model

    async def generate(
        self,
        messages: list[Message],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> LLMResponse:
        """Generate a completion."""
        use_model = model or self._model
        openai_messages = self._convert_messages(messages, use_model)

        kwargs: dict[str, Any] = {
            "model": use_model,
            "messages": openai_messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        # Create Langfuse generation for tracing
        generation = create_llm_generation(
            name="openai_chat_completion",
            model=use_model,
            input_messages=[
                {"role": m["role"], "content": str(m.get("content", ""))}
                for m in openai_messages
            ],
            model_parameters={
                "temperature": temperature,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
            },
            metadata={"provider": "openai"},
        )

        try:
            response = await self._client.chat.completions.create(**kwargs)

            choice = response.choices[0]
            usage = response.usage

            result = LLMResponse(
                content=choice.message.content or "",
                finish_reason=choice.finish_reason or "stop",
                usage=LLMUsage(
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    total_tokens=usage.total_tokens if usage else 0,
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
        openai_messages = self._convert_messages(messages, use_model)

        stream = await self._client.chat.completions.create(
            model=use_model,
            messages=openai_messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
        )

        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

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
        openai_messages = self._convert_messages(messages, use_model)
        tools = self._convert_functions(functions)

        # Create Langfuse generation for tracing
        generation = create_llm_generation(
            name="openai_chat_completion_with_tools",
            model=use_model,
            input_messages=[
                {"role": m["role"], "content": str(m.get("content", ""))}
                for m in openai_messages
            ],
            model_parameters={
                "temperature": temperature,
                "max_tokens": max_tokens,
                "tools": [f.name for f in functions],
            },
            metadata={"provider": "openai", "has_tools": True},
        )

        try:
            response = await self._client.chat.completions.create(
                model=use_model,
                messages=openai_messages,
                tools=tools,
                temperature=temperature,
                max_tokens=max_tokens,
            )

            choice = response.choices[0]
            usage = response.usage
            message = choice.message

            function_calls: list[FunctionCall] = []
            if message.tool_calls:
                for tool_call in message.tool_calls:
                    if hasattr(tool_call, "function") and tool_call.function:
                        func = tool_call.function
                        try:
                            args = json.loads(func.arguments)
                        except json.JSONDecodeError:
                            args = {}

                        function_calls.append(
                            FunctionCall(
                                name=func.name,
                                arguments=args,
                            )
                        )

            result = LLMResponseWithTools(
                content=message.content,
                finish_reason=choice.finish_reason or "stop",
                usage=LLMUsage(
                    prompt_tokens=usage.prompt_tokens if usage else 0,
                    completion_tokens=usage.completion_tokens if usage else 0,
                    total_tokens=usage.total_tokens if usage else 0,
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
        model: str,
    ) -> list[ChatCompletionMessageParam]:
        """Convert our Message format to OpenAI format."""
        result: list[ChatCompletionMessageParam] = []

        for msg in messages:
            if msg.role == MessageRole.SYSTEM:
                result.append({"role": "system", "content": msg.content})
            elif msg.role == MessageRole.ASSISTANT:
                result.append({"role": "assistant", "content": msg.content})
            elif msg.role == MessageRole.USER:
                # Check for multimodal content
                if (msg.images or msg.videos) and model in self._VISION_MODELS:
                    content: list[dict[str, Any]] = [
                        {"type": "text", "text": msg.content}
                    ]

                    # Add images
                    for image in msg.images or []:
                        if image.startswith("http://") or image.startswith("https://"):
                            content.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": image},
                                }
                            )
                        # Assume it's a file path or base64
                        elif Path(image).exists():
                            image_path = Path(image)
                            with image_path.open("rb") as f:
                                b64 = base64.b64encode(f.read()).decode()
                                ext = image_path.suffix.lstrip(".")
                                content.append(
                                    {
                                        "type": "image_url",
                                        "image_url": {
                                            "url": f"data:image/{ext};base64,{b64}"
                                        },
                                    }
                                )
                        else:
                            # Assume already base64
                            content.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": image},
                                }
                            )

                    result.append({"role": "user", "content": content})
                else:
                    result.append({"role": "user", "content": msg.content})

        return result

    def _convert_functions(
        self,
        functions: list[FunctionDefinition],
    ) -> list[ChatCompletionToolParam]:
        """Convert our FunctionDefinition to OpenAI tool format."""
        tools: list[ChatCompletionToolParam] = []

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
                    "type": "function",
                    "function": {
                        "name": func.name,
                        "description": func.description,
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
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
        return False  # OpenAI doesn't support video directly yet

    @property
    def supports_function_calling(self) -> bool:
        """Whether this model supports function/tool calling."""
        return self._model in self._FUNCTION_CALLING_MODELS

    @property
    def supports_json_mode(self) -> bool:
        """Whether this model supports JSON output mode."""
        return True  # Most recent OpenAI models support JSON mode

    @property
    def context_window(self) -> int:
        """Maximum context window in tokens."""
        return self._CONTEXT_WINDOWS.get(self._model, 8192)

    @property
    def default_model(self) -> str:
        """Default model identifier."""
        return self._model
