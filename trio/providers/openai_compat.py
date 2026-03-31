"""OpenAI-compatible LLM provider — works with OpenAI, Anthropic, Gemini, DeepSeek, Groq, OpenRouter, vLLM, etc.

BYOK (Bring Your Own Key) provider. Users configure their API key and base URL.
Supports any service with an OpenAI-compatible chat completions endpoint.

Known compatible services:
    - OpenAI (api.openai.com)
    - Anthropic via OpenAI proxy (api.anthropic.com)
    - Google Gemini (generativelanguage.googleapis.com)
    - DeepSeek (api.deepseek.com)
    - Groq (api.groq.com)
    - OpenRouter (openrouter.ai/api)
    - vLLM / LM Studio (localhost)
    - Any OpenAI-compatible endpoint
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import json
import logging
from typing import Any, AsyncIterator

import aiohttp

from trio.providers.base import BaseProvider, LLMResponse, StreamChunkData, ToolCall

logger = logging.getLogger(__name__)

# Default API base URLs for known providers
KNOWN_PROVIDERS = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "deepseek": "https://api.deepseek.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "siliconflow": "https://api.siliconflow.cn/v1",
    "minimax": "https://api.minimax.chat/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "dashscope": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}


class OpenAICompatProvider(BaseProvider):
    """Generic OpenAI-compatible provider for BYOK usage.

    Config keys:
        apiKey: API key for authentication
        apiBase: Base URL (auto-detected for known providers)
        default_model: Default model name
        provider_name: Name hint for auto-detecting apiBase
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.api_key = config.get("apiKey", "")
        self.provider_name = config.get("provider_name", "custom")
        self.api_base = config.get("apiBase", KNOWN_PROVIDERS.get(self.provider_name, ""))
        self.default_model = config.get("default_model", "")
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=180)
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._session = aiohttp.ClientSession(timeout=timeout, headers=headers)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    # ── Full response ──────────────────────────────────

    async def generate(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        use_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools

        try:
            session = await self._get_session()
            url = f"{self.api_base}/chat/completions"
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    return LLMResponse(
                        content=f"API Error ({resp.status}): {error_text}",
                        finish_reason="error",
                        model=use_model,
                    )
                data = await resp.json()
                choice = data.get("choices", [{}])[0]
                message = choice.get("message", {})

                # Parse tool calls if present
                tool_calls = []
                for tc in message.get("tool_calls", []):
                    try:
                        args = json.loads(tc["function"]["arguments"])
                    except (json.JSONDecodeError, KeyError):
                        args = {}
                    tool_calls.append(ToolCall(
                        id=tc.get("id", ""),
                        name=tc["function"]["name"],
                        arguments=args,
                    ))

                usage = data.get("usage", {})
                return LLMResponse(
                    content=message.get("content", "") or "",
                    tool_calls=tool_calls,
                    finish_reason=choice.get("finish_reason", "stop"),
                    model=data.get("model", use_model),
                    usage={
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "completion_tokens": usage.get("completion_tokens", 0),
                    },
                )
        except aiohttp.ClientConnectorError:
            return LLMResponse(
                content=f"Error: Cannot connect to {self.api_base}",
                finish_reason="error",
                model=use_model,
            )
        except Exception as e:
            logger.error(f"OpenAI-compat generate error: {e}")
            return LLMResponse(content=f"Error: {e}", finish_reason="error", model=use_model)

    # ── Streaming response ─────────────────────────────

    async def stream_generate(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamChunkData]:
        use_model = model or self.default_model
        payload: dict[str, Any] = {
            "model": use_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        try:
            session = await self._get_session()
            url = f"{self.api_base}/chat/completions"
            async with session.post(url, json=payload) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    yield StreamChunkData(
                        text=f"API Error ({resp.status}): {error_text}",
                        is_final=True,
                    )
                    return

                async for line in resp.content:
                    line = line.decode("utf-8", errors="ignore").strip()
                    if not line or line == "data: [DONE]":
                        if line == "data: [DONE]":
                            yield StreamChunkData(text="", is_final=True)
                            return
                        continue

                    if line.startswith("data: "):
                        line = line[6:]

                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    choice = data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    text = delta.get("content", "") or ""
                    finish = choice.get("finish_reason")

                    if text:
                        yield StreamChunkData(text=text)

                    if finish:
                        yield StreamChunkData(
                            text="",
                            is_final=True,
                            metadata={"model": data.get("model", use_model)},
                        )
                        return

        except aiohttp.ClientConnectorError:
            yield StreamChunkData(
                text=f"Error: Cannot connect to {self.api_base}",
                is_final=True,
            )
        except Exception as e:
            logger.error(f"OpenAI-compat stream error: {e}")
            yield StreamChunkData(text=f"Error: {e}", is_final=True)

    # ── Model listing ──────────────────────────────────

    async def list_models(self) -> list[str]:
        try:
            session = await self._get_session()
            async with session.get(f"{self.api_base}/models") as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return [m["id"] for m in data.get("data", [])]
                return []
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []

    def supports_tools(self) -> bool:
        return True
