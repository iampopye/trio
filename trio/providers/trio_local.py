"""Trio Local Provider — use the built-in Trio LLM for agent inference."""

from typing import Any, AsyncIterator

from trio.providers.base import BaseProvider, LLMResponse, StreamChunkData


class TrioLocalProvider(BaseProvider):
    """Use a locally trained Trio model as an LLM provider.

    Supports trio-nano, trio-small, and trio-medium presets.
    Requires a trained checkpoint in the default checkpoint directory.
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._engine = None
        self.default_model = config.get("default_model", "trio-nano")

    def _get_engine(self, model: str | None = None):
        """Lazy-load the Trio model engine."""
        if self._engine is None:
            try:
                import os
                import torch
                from trio_model.config import get_config
                from trio_model.inference.server import TrioEngine

                preset = (model or self.default_model).replace("trio-", "")
                if preset not in ("nano", "small", "medium"):
                    preset = "nano"

                cfg = get_config(preset)
                # Find best checkpoint
                ckpt_path = None
                for candidate in [
                    os.path.join(cfg.checkpoint_dir, "sft", "trio_latest.pt"),
                    os.path.join(cfg.checkpoint_dir, "trio_latest.pt"),
                ]:
                    if os.path.exists(candidate):
                        ckpt_path = candidate
                        break
                if not ckpt_path:
                    ckpt_path = os.path.join(cfg.checkpoint_dir, "trio_latest.pt")

                self._engine = TrioEngine(ckpt_path, preset=preset)
            except ImportError as e:
                raise RuntimeError(
                    f"Trio model dependencies not installed: {e}\n"
                    "Install with: pip install torch tiktoken"
                )
        return self._engine

    async def generate(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Generate a response using the local Trio model."""
        engine = self._get_engine(model)

        # Convert messages to Trio format
        trio_messages = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                trio_messages.append({"role": "system", "content": content})
            elif role in ("user", "human"):
                trio_messages.append({"role": "human", "content": content})
            elif role in ("assistant", "trio"):
                trio_messages.append({"role": "trio", "content": content})

        response_text = engine.chat(
            trio_messages,
            max_new_tokens=min(max_tokens, 500),
            temperature=temperature,
        )

        return LLMResponse(
            content=response_text,
            model=model or self.default_model,
            finish_reason="stop",
        )

    async def stream_generate(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamChunkData]:
        """Stream response (Trio model generates all at once, so we yield one chunk)."""
        response = await self.generate(messages, model, tools, temperature, max_tokens)
        # Simulate streaming by yielding the full response as one chunk
        yield StreamChunkData(text=response.content, is_final=True)

    async def list_models(self) -> list[str]:
        """List available Trio model presets."""
        return ["trio-nano", "trio-small", "trio-medium"]

    async def close(self) -> None:
        self._engine = None
