"""Base provider interface and registry."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator, Any


@dataclass
class ToolCall:
    """A tool call requested by the LLM."""
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    """Standardized response from any LLM provider."""
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    usage: dict[str, int] = field(default_factory=dict)
    model: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamChunkData:
    """A single chunk from a streaming response."""
    text: str = ""
    is_final: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseProvider(ABC):
    """Abstract base for all LLM providers.

    Subclasses must implement:
        - generate(): Full response (non-streaming)
        - stream_generate(): Async streaming chunks
        - list_models(): Available models

    Optional overrides:
        - supports_vision(): Whether provider handles images
        - supports_tools(): Whether provider handles tool calling
        - close(): Cleanup resources
    """

    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.default_model = config.get("default_model", "")

    @abstractmethod
    async def generate(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Generate a complete response."""
        ...

    @abstractmethod
    async def stream_generate(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamChunkData]:
        """Stream response chunks."""
        ...

    @abstractmethod
    async def list_models(self) -> list[str]:
        """List available models."""
        ...

    def supports_vision(self) -> bool:
        return False

    def supports_tools(self) -> bool:
        return False

    async def close(self) -> None:
        """Cleanup provider resources."""
        pass


class ProviderRegistry:
    """Registry of available LLM providers."""

    _providers: dict[str, type[BaseProvider]] = {}

    @classmethod
    def register(cls, name: str, provider_cls: type[BaseProvider]) -> None:
        cls._providers[name] = provider_cls

    @classmethod
    def create(cls, name: str, config: dict[str, Any]) -> BaseProvider:
        """Create a provider instance by name."""
        if name not in cls._providers:
            available = ", ".join(cls._providers.keys()) or "none"
            raise ValueError(f"Unknown provider '{name}'. Available: {available}")
        return cls._providers[name](config)

    @classmethod
    def available(cls) -> list[str]:
        return list(cls._providers.keys())

    @classmethod
    def get_class(cls, name: str) -> type[BaseProvider] | None:
        return cls._providers.get(name)


def register_all_providers() -> None:
    """Register all built-in providers."""
    from trio.providers.ollama import OllamaProvider
    from trio.providers.openai_compat import OpenAICompatProvider
    from trio.providers.local import LocalProvider

    ProviderRegistry.register("trio", LocalProvider)                # Built-in Trio LLM (native GGUF, no Ollama)
    ProviderRegistry.register("local", LocalProvider)               # Alias
    ProviderRegistry.register("ollama", OllamaProvider)
    ProviderRegistry.register("openai", OpenAICompatProvider)       # OpenAI GPT
    ProviderRegistry.register("anthropic", OpenAICompatProvider)    # Claude
    ProviderRegistry.register("gemini", OpenAICompatProvider)       # Google Gemini
    ProviderRegistry.register("openrouter", OpenAICompatProvider)   # OpenRouter (all models)
    ProviderRegistry.register("deepseek", OpenAICompatProvider)
    ProviderRegistry.register("groq", OpenAICompatProvider)
    ProviderRegistry.register("siliconflow", OpenAICompatProvider)
    ProviderRegistry.register("minimax", OpenAICompatProvider)
    ProviderRegistry.register("moonshot", OpenAICompatProvider)
    ProviderRegistry.register("dashscope", OpenAICompatProvider)
    ProviderRegistry.register("custom", OpenAICompatProvider)       # Any OpenAI-compatible
