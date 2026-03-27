"""Native GGUF inference provider — runs models locally via llama-cpp-python.

No Ollama needed. Loads .gguf files directly using llama.cpp bindings.
Supports CPU and GPU (CUDA, Metal, ROCm) inference.

Usage in config.json:
    "providers": {
        "local": {
            "model_path": "path/to/model.gguf",   # or auto-detected
            "n_ctx": 8192,
            "n_gpu_layers": -1,                     # -1 = all layers on GPU
            "chat_format": "chatml"
        }
    }
"""

import asyncio
import logging
import os
import re
import time
from functools import partial
from pathlib import Path
from typing import Any, AsyncIterator

from trio.providers.base import BaseProvider, LLMResponse, StreamChunkData

logger = logging.getLogger(__name__)


# ── Model Discovery ──────────────────────────────────────────────────────────

# Known trio model filenames, in preference order per model name
KNOWN_MODELS = {
    "trio-max": [
        "trio-max-q4_k_m.gguf",
        "trio-max-q5_k_m.gguf",
        "trio-max-q8_0.gguf",
        "trio-max.gguf",
    ],
    "trio-nano": [
        "trio-nano-q4_k_m.gguf",
        "trio-nano-q5_k_m.gguf",
        "trio-nano-q8_0.gguf",
        "trio-nano.gguf",
    ],
}


def _find_gguf_model(model_name: str = "", explicit_path: str = "") -> str | None:
    """Auto-detect a GGUF model file.

    Search order:
        1. Explicit path from config (if provided and exists)
        2. ~/.trio/models/ directory
        3. Project models/ directory (D:/models/trio/models/)
        4. Current working directory

    For named models (trio-max, trio-nano), searches for known filenames.
    Otherwise returns the first .gguf file found.
    """
    if explicit_path and os.path.isfile(explicit_path):
        return explicit_path

    search_dirs = [
        Path.home() / ".trio" / "models",
        Path(__file__).resolve().parent.parent.parent / "models",
        Path.cwd(),
    ]

    # If a specific model is requested, look for known filenames
    candidates = KNOWN_MODELS.get(model_name, [])

    for search_dir in search_dirs:
        if not search_dir.is_dir():
            continue

        # Try known filenames first
        for filename in candidates:
            path = search_dir / filename
            if path.is_file():
                return str(path)

        # Try a glob match on the model name
        if model_name:
            pattern = f"{model_name}*.gguf"
            matches = sorted(search_dir.glob(pattern))
            if matches:
                return str(matches[0])

    # Last resort: find any .gguf file in search directories
    if not model_name or model_name in ("trio-max", "trio-nano"):
        for search_dir in search_dirs:
            if not search_dir.is_dir():
                continue
            gguf_files = sorted(search_dir.glob("*.gguf"))
            if gguf_files:
                return str(gguf_files[0])

    return None


def _list_gguf_models() -> list[str]:
    """List all available GGUF model files across search directories."""
    search_dirs = [
        Path.home() / ".trio" / "models",
        Path(__file__).resolve().parent.parent.parent / "models",
    ]
    found = []
    seen = set()
    for search_dir in search_dirs:
        if not search_dir.is_dir():
            continue
        for gguf_file in sorted(search_dir.glob("*.gguf")):
            name = gguf_file.name
            if name not in seen:
                seen.add(name)
                found.append(name)
    return found


# ── Provider ─────────────────────────────────────────────────────────────────

class LocalProvider(BaseProvider):
    """Native GGUF model inference -- no Ollama needed.

    Uses llama-cpp-python to load and run GGUF models directly.
    Supports CPU inference out of the box, GPU acceleration with
    appropriate llama-cpp-python build (CUDA, Metal, ROCm).

    Config keys:
        model_path:    Explicit path to .gguf file (auto-detected if empty)
        n_ctx:         Context window size (default 8192)
        n_gpu_layers:  GPU layers to offload (-1 = all, 0 = CPU only)
        chat_format:   Chat template format (default "chatml")
        default_model: Model name hint for auto-detection (e.g. "trio-nano")
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self.model_path = config.get("model_path", "")
        self.n_ctx = config.get("n_ctx", 8192)
        self.n_gpu_layers = config.get("n_gpu_layers", -1)
        self.chat_format = config.get("chat_format", "chatml")
        self.default_model = config.get("default_model", "trio-nano")
        self._model = None
        self._model_name = ""
        self._executor = None

    def _load_model(self, model: str | None = None) -> None:
        """Lazy-load the GGUF model into memory."""
        try:
            from llama_cpp import Llama
        except ImportError:
            raise RuntimeError(
                "llama-cpp-python is not installed.\n"
                "Install with: pip install llama-cpp-python\n"
                "For GPU support: CMAKE_ARGS=\"-DGGML_CUDA=on\" pip install llama-cpp-python"
            )

        # Resolve model path
        model_hint = model or self.default_model
        resolved_path = _find_gguf_model(
            model_name=model_hint,
            explicit_path=self.model_path,
        )

        if not resolved_path:
            search_dirs = [
                str(Path.home() / ".trio" / "models"),
                str(Path(__file__).resolve().parent.parent.parent / "models"),
            ]
            raise FileNotFoundError(
                f"No GGUF model found for '{model_hint}'.\n"
                f"Searched: {', '.join(search_dirs)}\n\n"
                "To get started:\n"
                "  1. Download a GGUF model (e.g. from HuggingFace)\n"
                "  2. Place it in ~/.trio/models/\n"
                "  3. Or set model_path in your config:\n"
                '     trio config set providers.local.model_path "/path/to/model.gguf"'
            )

        model_size_mb = os.path.getsize(resolved_path) / (1024 * 1024)
        model_filename = os.path.basename(resolved_path)
        print(f"[trio.ai] Loading {model_filename} ({model_size_mb:.0f} MB)...")

        start = time.time()
        # Suppress llama.cpp warnings (e.g. n_ctx < n_ctx_train)
        import io
        import sys
        _stderr = sys.stderr
        sys.stderr = io.StringIO()
        try:
            self._model = Llama(
                model_path=resolved_path,
                n_ctx=self.n_ctx,
                n_gpu_layers=self.n_gpu_layers,
                verbose=False,
                chat_format=self.chat_format,
            )
        finally:
            sys.stderr = _stderr
        elapsed = time.time() - start

        self._model_name = model_filename
        self.model_path = resolved_path

        # Report load info
        gpu_info = ""
        if self.n_gpu_layers != 0:
            gpu_info = f", GPU layers: {'all' if self.n_gpu_layers == -1 else self.n_gpu_layers}"
        print(f"[trio.ai] Model loaded in {elapsed:.1f}s (ctx: {self.n_ctx}{gpu_info})")

    def _ensure_model(self, model: str | None = None) -> None:
        """Ensure model is loaded, loading it if needed."""
        if self._model is None:
            self._load_model(model)

    @staticmethod
    def _format_messages(messages: list[dict]) -> list[dict]:
        """Convert messages to llama-cpp chat format.

        Normalizes role names: user/human -> user, assistant/trio -> assistant.
        Appends /no_think to the last user message to disable the model's
        internal reasoning mode, which produces <think> blocks and slows
        response time significantly.
        """
        formatted = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Normalize roles for ChatML template
            if role in ("human", "user"):
                role = "user"
            elif role in ("trio", "assistant", "bot"):
                role = "assistant"
            elif role == "system":
                role = "system"
            else:
                role = "user"

            formatted.append({"role": role, "content": content})

        # Disable thinking mode for faster direct responses
        if formatted and formatted[-1]["role"] == "user":
            formatted[-1]["content"] += " /no_think"

        return formatted

    @staticmethod
    def _strip_think_tags(text: str) -> str:
        """Strip <think>...</think> reasoning blocks from model output.

        Also handles incomplete think blocks (when max_tokens cuts off
        before </think> appears).
        """
        # Remove complete <think>...</think> blocks
        cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        # Remove incomplete <think> blocks (no closing tag — truncated by max_tokens)
        cleaned = re.sub(r"<think>.*$", "", cleaned, flags=re.DOTALL).strip()
        return cleaned if cleaned else text

    # ── Full response (non-streaming) ──────────────────

    async def generate(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> LLMResponse:
        """Generate a complete response using the local GGUF model."""
        try:
            self._ensure_model(model)
        except (RuntimeError, FileNotFoundError) as e:
            return LLMResponse(
                content=f"Error: {e}",
                finish_reason="error",
                model=model or self.default_model,
            )

        formatted = self._format_messages(messages)

        # llama-cpp-python is synchronous; run in executor to avoid blocking
        loop = asyncio.get_event_loop()
        try:
            start = time.time()
            result = await loop.run_in_executor(
                self._executor,
                partial(
                    self._model.create_chat_completion,
                    messages=formatted,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=False,
                ),
            )
            elapsed = time.time() - start

            # Extract response content
            choice = result.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = self._strip_think_tags(message.get("content", "").strip())
            finish_reason = choice.get("finish_reason", "stop")

            # Usage stats
            usage_data = result.get("usage", {})
            prompt_tokens = usage_data.get("prompt_tokens", 0)
            completion_tokens = usage_data.get("completion_tokens", 0)

            # Calculate tokens/second
            tokens_per_sec = (
                completion_tokens / elapsed if elapsed > 0 and completion_tokens > 0 else 0
            )

            return LLMResponse(
                content=content,
                finish_reason=finish_reason,
                model=self._model_name or (model or self.default_model),
                usage={
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
                metadata={
                    "response_time": round(elapsed, 2),
                    "tokens_per_second": round(tokens_per_sec, 1),
                    "provider": "local",
                    "engine": "llama-cpp-python",
                },
            )
        except Exception as e:
            logger.error(f"Local generate error: {e}")
            return LLMResponse(
                content=f"Error during generation: {e}",
                finish_reason="error",
                model=self._model_name or (model or self.default_model),
            )

    # ── Streaming response ─────────────────────────────

    async def stream_generate(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamChunkData]:
        """Stream response chunks from the local GGUF model."""
        try:
            self._ensure_model(model)
        except (RuntimeError, FileNotFoundError) as e:
            yield StreamChunkData(text=f"Error: {e}", is_final=True)
            return

        formatted = self._format_messages(messages)

        # Create the streaming completion in executor (initial call)
        loop = asyncio.get_event_loop()

        in_think_block = False

        try:
            # Start streaming generation (this returns an iterator)
            stream_iter = await loop.run_in_executor(
                self._executor,
                partial(
                    self._model.create_chat_completion,
                    messages=formatted,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    stream=True,
                ),
            )

            # Iterate over streamed chunks
            # llama-cpp stream is a synchronous iterator; wrap in executor
            def _next_chunk(it):
                try:
                    return next(it)
                except StopIteration:
                    return None

            while True:
                chunk = await loop.run_in_executor(
                    self._executor,
                    partial(_next_chunk, stream_iter),
                )

                if chunk is None:
                    # Stream finished
                    yield StreamChunkData(
                        text="",
                        is_final=True,
                        metadata={
                            "model": self._model_name,
                            "provider": "local",
                        },
                    )
                    return

                # Extract text from chunk
                choice = chunk.get("choices", [{}])[0]
                delta = choice.get("delta", {})
                text = delta.get("content", "") or ""
                finish = choice.get("finish_reason")

                if text:
                    # Filter out <think> blocks from streaming output
                    if "<think>" in text:
                        in_think_block = True
                    if in_think_block:
                        if "</think>" in text:
                            # Think block ended in this chunk
                            text = text.split("</think>", 1)[-1]
                            in_think_block = False
                            if text:
                                yield StreamChunkData(text=text)
                        # else: still inside think block, skip
                    else:
                        yield StreamChunkData(text=text)

                if finish:
                    yield StreamChunkData(
                        text="",
                        is_final=True,
                        metadata={
                            "model": self._model_name,
                            "provider": "local",
                            "finish_reason": finish,
                        },
                    )
                    return

        except Exception as e:
            logger.error(f"Local stream error: {e}")
            yield StreamChunkData(text=f"Error: {e}", is_final=True)

    # ── Model management ───────────────────────────────

    async def list_models(self) -> list[str]:
        """List all available GGUF models."""
        models = _list_gguf_models()
        if not models and self._model_name:
            return [self._model_name]
        return models if models else ["(no GGUF models found)"]

    def supports_vision(self) -> bool:
        return False

    def supports_tools(self) -> bool:
        return False

    async def close(self) -> None:
        """Release the model from memory."""
        if self._model is not None:
            del self._model
            self._model = None
            self._model_name = ""
            logger.info("Local GGUF model unloaded.")
