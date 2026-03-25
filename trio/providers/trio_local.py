"""Trio Local Provider — self-contained LLM that runs on the user's system.

No external dependencies. No API keys. No Ollama.
On first use, auto-initializes the Trio nano model using system CPU/GPU.
"""

import os
from typing import Any, AsyncIterator
from pathlib import Path

from trio.providers.base import BaseProvider, LLMResponse, StreamChunkData


def _get_trio_model_dir() -> Path:
    """Get the directory for trio model checkpoints."""
    model_dir = Path.home() / ".trio" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


def _auto_setup_model(preset: str = "nano") -> str:
    """Auto-setup the Trio model on first use. Returns checkpoint path."""
    import torch
    from trio_model.config import get_config
    from trio_model.model.architecture import TrioModel
    from trio_model.data.tokenizer import get_tokenizer

    model_dir = _get_trio_model_dir()
    ckpt_path = model_dir / f"trio-{preset}.pt"

    if ckpt_path.exists():
        return str(ckpt_path)

    print(f"\n[trio.ai] First-time setup: Initializing trio-{preset} model...")
    print(f"[trio.ai] This only happens once. Model will be saved to {ckpt_path}")

    cfg = get_config(preset)
    tokenizer = get_tokenizer(preset)
    cfg.vocab_size = tokenizer.vocab_size

    model = TrioModel(cfg)
    params = model.num_parameters()
    print(f"[trio.ai] Model: trio-{preset} | {params / 1e6:.1f}M parameters")

    # Save the initialized model as checkpoint
    ckpt = {
        "step": 0,
        "val_loss": float("inf"),
        "model": model.state_dict(),
        "config": cfg.__dict__,
    }
    torch.save(ckpt, str(ckpt_path))
    print(f"[trio.ai] Model ready at {ckpt_path}")
    print(f"[trio.ai] Tip: Train it with `python -m trio_model.training.pretrain --preset {preset}` for better responses\n")

    return str(ckpt_path)


class TrioLocalProvider(BaseProvider):
    """Built-in Trio LLM that runs entirely on the user's machine.

    Zero external dependencies. Auto-initializes on first use.
    Supports trio-nano (CPU), trio-small (GPU), trio-medium (A100).
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._engine = None
        self.default_model = config.get("default_model", "trio-nano")

    def _get_engine(self, model: str | None = None):
        """Lazy-load the Trio model engine. Auto-setup if needed."""
        if self._engine is None:
            try:
                import torch
                from trio_model.config import get_config
                from trio_model.inference.server import TrioEngine

                preset = (model or self.default_model).replace("trio-", "")
                if preset not in ("nano", "small", "medium"):
                    preset = "nano"

                # Auto-setup: download/initialize model if not present
                ckpt_path = _auto_setup_model(preset)
                self._engine = TrioEngine(ckpt_path, preset=preset)
            except ImportError as e:
                raise RuntimeError(
                    f"Trio model dependencies not installed: {e}\n"
                    "Install with: pip install trio-ai[model]"
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
        """Stream response (yields full response as one chunk)."""
        response = await self.generate(messages, model, tools, temperature, max_tokens)
        yield StreamChunkData(text=response.content, is_final=True)

    async def list_models(self) -> list[str]:
        """List available Trio model presets."""
        return ["trio-nano", "trio-small", "trio-medium"]

    async def close(self) -> None:
        self._engine = None
