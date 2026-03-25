"""Trio Local Provider — self-contained LLM that runs on the user's system.

No external dependencies. No API keys. No Ollama.
Auto-detects system resources and picks the best model size.
On first use, auto-initializes the model using system CPU/GPU.
If the model is untrained, uses a smart fallback response engine.
"""

import os
import time
from typing import Any, AsyncIterator
from pathlib import Path

from trio.providers.base import BaseProvider, LLMResponse, StreamChunkData


# ── Resource Detection ────────────────────────────────────────────────────────

def _detect_system_resources() -> dict:
    """Detect available CPU, RAM, and GPU resources."""
    resources = {
        "cpu_cores": os.cpu_count() or 1,
        "ram_gb": 0,
        "gpu_available": False,
        "gpu_name": None,
        "gpu_vram_gb": 0,
    }

    # RAM detection
    try:
        import psutil
        resources["ram_gb"] = round(psutil.virtual_memory().total / (1024**3), 1)
    except ImportError:
        # Fallback: read from OS
        try:
            if os.name == "nt":
                import ctypes
                kernel32 = ctypes.windll.kernel32
                c_ulonglong = ctypes.c_ulonglong
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [
                        ("dwLength", ctypes.c_ulong),
                        ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", c_ulonglong),
                        ("ullAvailPhys", c_ulonglong),
                        ("ullTotalPageFile", c_ulonglong),
                        ("ullAvailPageFile", c_ulonglong),
                        ("ullTotalVirtual", c_ulonglong),
                        ("ullAvailVirtual", c_ulonglong),
                        ("ullAvailExtendedVirtual", c_ulonglong),
                    ]
                stat = MEMORYSTATUSEX()
                stat.dwLength = ctypes.sizeof(stat)
                kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                resources["ram_gb"] = round(stat.ullTotalPhys / (1024**3), 1)
        except Exception:
            resources["ram_gb"] = 4  # safe default

    # GPU detection
    try:
        import torch
        if torch.cuda.is_available():
            resources["gpu_available"] = True
            resources["gpu_name"] = torch.cuda.get_device_name(0)
            resources["gpu_vram_gb"] = round(torch.cuda.get_device_properties(0).total_mem / (1024**3), 1)
    except Exception:
        pass

    return resources


def _auto_select_preset(resources: dict) -> str:
    """Pick the best model preset based on system resources."""
    if resources["gpu_available"] and resources["gpu_vram_gb"] >= 30:
        return "medium"   # ~1B params, needs A100/H100
    elif resources["gpu_available"] and resources["gpu_vram_gb"] >= 8:
        return "small"    # ~125M params, needs T4+
    else:
        return "nano"     # ~1M params, runs on any CPU


# ── Model Directory ───────────────────────────────────────────────────────────

def _get_trio_model_dir() -> Path:
    """Get the directory for trio model checkpoints."""
    model_dir = Path.home() / ".trio" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


# ── Auto Setup ────────────────────────────────────────────────────────────────

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

    ckpt = {
        "step": 0,
        "val_loss": float("inf"),
        "model": model.state_dict(),
        "config": cfg.__dict__,
    }
    torch.save(ckpt, str(ckpt_path))
    print(f"[trio.ai] Model ready at {ckpt_path}")
    print(f"[trio.ai] Tip: Train with `python -m trio_model.training.pretrain --preset {preset}` for smarter responses\n")

    return str(ckpt_path)


# ── Fallback Response Engine (for untrained models) ──────────────────────────

class _FallbackEngine:
    """Smart fallback that gives useful responses when the neural model is untrained.

    Uses keyword matching and templates to handle common queries.
    This makes trio usable immediately on install, while the user trains the model.
    """

    GREETINGS = {"hello", "hi", "hey", "hola", "namaste", "sup", "yo", "greetings"}
    FAREWELLS = {"bye", "goodbye", "exit", "quit", "see ya", "later"}

    RESPONSES = {
        "greeting": (
            "Hello! I'm Trio, your local AI assistant. I'm running on your system "
            "with no external dependencies.\n\n"
            "I'm currently using my base knowledge (untrained). Train me for much "
            "better responses:\n"
            "  python -m trio_model.training.pretrain --preset nano\n\n"
            "How can I help you?"
        ),
        "who_are_you": (
            "I'm Trio AI - an open-source AI assistant that runs entirely on your machine.\n\n"
            "- No API keys needed\n"
            "- No cloud dependency\n"
            "- Your data stays local\n"
            "- Built with a custom transformer architecture\n\n"
            "I'm currently running with base weights. Train me to unlock my full potential!"
        ),
        "capabilities": (
            "Here's what I can do:\n\n"
            "- Answer questions and have conversations\n"
            "- Help with coding, writing, and analysis\n"
            "- Use tools: web search, math, shell, file operations\n"
            "- Work across platforms: CLI, Discord, Telegram, Signal\n"
            "- Access 1,600+ built-in skills\n\n"
            "Train me for better responses: python -m trio_model.training.pretrain --preset nano"
        ),
        "help": (
            "Quick commands:\n\n"
            "  trioai agent           - Chat with me\n"
            "  trioai agent -m \"msg\"  - Single message\n"
            "  trioai status          - System status\n"
            "  trioai provider add    - Add cloud LLM\n"
            "  trioai onboard         - Re-run setup\n\n"
            "To train me: python -m trio_model.training.pretrain --preset nano"
        ),
        "farewell": "Goodbye! Run `trioai agent` anytime to chat again.",
        "default": (
            "I understand your question, but I need training to give you a proper answer.\n\n"
            "Right now I'm running with base weights (untrained). To train me:\n"
            "  python -m trio_model.training.pretrain --preset nano\n\n"
            "This takes a few hours on CPU. After training, I'll give much better responses.\n\n"
            "In the meantime, you can:\n"
            "- Add a cloud provider: trioai provider add\n"
            "- Use Ollama locally: trioai provider add (select ollama)"
        ),
    }

    def chat(self, messages: list[dict], **kwargs) -> str:
        """Generate a response using keyword matching."""
        if not messages:
            return self.RESPONSES["greeting"]

        last_msg = messages[-1].get("content", "").lower().strip()
        words = set(last_msg.split())

        # Check greetings
        if words & self.GREETINGS or last_msg in self.GREETINGS:
            return self.RESPONSES["greeting"]

        # Check farewells
        if words & self.FAREWELLS:
            return self.RESPONSES["farewell"]

        # Check identity questions
        if any(q in last_msg for q in ["who are you", "what are you", "your name", "about yourself"]):
            return self.RESPONSES["who_are_you"]

        # Check capability questions
        if any(q in last_msg for q in ["what can you", "help me", "capabilities", "what do you do", "features"]):
            return self.RESPONSES["capabilities"]

        # Check help
        if last_msg in ("help", "commands", "how to use"):
            return self.RESPONSES["help"]

        # Default
        return self.RESPONSES["default"]


# ── Provider ──────────────────────────────────────────────────────────────────

class TrioLocalProvider(BaseProvider):
    """Built-in Trio LLM that runs entirely on the user's machine.

    Zero external dependencies. Auto-detects resources. Auto-initializes on first use.
    Uses smart fallback responses when model is untrained.
    """

    def __init__(self, config: dict[str, Any]):
        super().__init__(config)
        self._engine = None
        self._is_trained = False
        self._fallback = _FallbackEngine()
        self.default_model = config.get("default_model", "trio-nano")

    def _get_engine(self, model: str | None = None):
        """Lazy-load the Trio model engine. Auto-setup if needed."""
        if self._engine is not None:
            return self._engine

        try:
            import torch
            from trio_model.inference.server import TrioEngine

            # Auto-detect best preset for this system
            requested_preset = (model or self.default_model).replace("trio-", "")
            if requested_preset not in ("nano", "small", "medium"):
                requested_preset = "nano"

            resources = _detect_system_resources()
            best_preset = _auto_select_preset(resources)

            # Downgrade if user picked too large a model for their system
            preset_order = ["nano", "small", "medium"]
            if preset_order.index(requested_preset) > preset_order.index(best_preset):
                print(f"[trio.ai] Your system has {resources['ram_gb']}GB RAM", end="")
                if resources["gpu_available"]:
                    print(f", GPU: {resources['gpu_name']} ({resources['gpu_vram_gb']}GB VRAM)")
                else:
                    print(" (no GPU)")
                print(f"[trio.ai] Switching from trio-{requested_preset} to trio-{best_preset} for best performance")
                requested_preset = best_preset

            # Auto-setup model
            ckpt_path = _auto_setup_model(requested_preset)

            # Check if model is trained (step > 0)
            ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
            step = ckpt.get("step", 0)
            self._is_trained = step > 0

            if self._is_trained:
                self._engine = TrioEngine(ckpt_path, preset=requested_preset)
                print(f"[trio.ai] Model loaded (trained, step={step})")
            else:
                self._engine = self._fallback
                print(f"[trio.ai] Model is untrained (step=0) — using smart fallback responses")
                print(f"[trio.ai] Train for better responses: python -m trio_model.training.pretrain --preset {requested_preset}")

            # Update default model to what we actually loaded
            self.default_model = f"trio-{requested_preset}"

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
        start = time.time()
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

        if self._is_trained:
            response_text = engine.chat(
                trio_messages,
                max_new_tokens=min(max_tokens, 500),
                temperature=temperature,
            )
        else:
            response_text = engine.chat(trio_messages)

        elapsed = time.time() - start

        return LLMResponse(
            content=response_text,
            model=model or self.default_model,
            finish_reason="stop",
            metadata={"response_time": round(elapsed, 2)},
        )

    async def stream_generate(
        self,
        messages: list[dict],
        model: str | None = None,
        tools: list[dict] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
    ) -> AsyncIterator[StreamChunkData]:
        """Stream response (yields full response as one chunk for now)."""
        response = await self.generate(messages, model, tools, temperature, max_tokens)
        yield StreamChunkData(text=response.content, is_final=True)

    async def list_models(self) -> list[str]:
        """List available Trio model presets."""
        return ["trio-nano", "trio-small", "trio-medium"]

    async def close(self) -> None:
        self._engine = None
        self._is_trained = False
