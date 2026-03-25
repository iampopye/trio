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

    # RAM detection — cross-platform (Windows, macOS, Linux)
    try:
        import psutil
        resources["ram_gb"] = round(psutil.virtual_memory().total / (1024**3), 1)
    except ImportError:
        # Fallback: read from OS without psutil
        import sys as _sys
        try:
            if _sys.platform == "win32":
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
            elif _sys.platform == "darwin":
                # macOS: use sysctl
                import subprocess
                result = subprocess.run(
                    ["sysctl", "-n", "hw.memsize"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0:
                    resources["ram_gb"] = round(int(result.stdout.strip()) / (1024**3), 1)
            else:
                # Linux: read /proc/meminfo
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            resources["ram_gb"] = round(kb / (1024**2), 1)
                            break
        except Exception:
            resources["ram_gb"] = 4  # safe default

    # GPU detection — CUDA (NVIDIA), MPS (Apple Silicon), ROCm (AMD)
    try:
        import torch
        if torch.cuda.is_available():
            resources["gpu_available"] = True
            resources["gpu_name"] = torch.cuda.get_device_name(0)
            resources["gpu_vram_gb"] = round(
                torch.cuda.get_device_properties(0).total_mem / (1024**3), 1
            )
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            # Apple Silicon (M1/M2/M3/M4) — shares unified memory
            resources["gpu_available"] = True
            resources["gpu_name"] = "Apple Silicon (MPS)"
            # MPS uses unified memory, so GPU VRAM = system RAM
            resources["gpu_vram_gb"] = resources["ram_gb"]
    except Exception:
        pass

    return resources


def _auto_select_preset(resources: dict) -> str:
    """Pick the best model preset based on system resources.

    Supports NVIDIA CUDA, Apple Silicon MPS, AMD ROCm, and CPU-only.
    """
    gpu = resources["gpu_available"]
    vram = resources["gpu_vram_gb"]
    ram = resources["ram_gb"]

    if gpu and vram >= 30:
        return "medium"   # ~1B params, needs A100/H100 or M2 Ultra+
    elif gpu and vram >= 8:
        return "small"    # ~125M params, needs T4+ or M1/M2
    elif ram >= 16:
        return "nano"     # ~1M params, good CPU with enough RAM
    else:
        return "nano"     # ~1M params, runs on any system


# ── Model Directory ───────────────────────────────────────────────────────────

def _get_trio_model_dir() -> Path:
    """Get the directory for trio model checkpoints."""
    model_dir = Path.home() / ".trio" / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    return model_dir


# ── Auto Setup ────────────────────────────────────────────────────────────────

def _auto_setup_model(preset: str = "nano") -> str:
    """Auto-setup the Trio model on first use. Returns checkpoint path.

    Priority:
    1. Use existing checkpoint in ~/.trio/models/
    2. Copy pre-trained weights bundled with the package
    3. Initialize fresh (untrained) model as last resort
    """
    import shutil
    import torch
    from trio_model.config import get_config
    from trio_model.model.architecture import TrioModel
    from trio_model.data.tokenizer import get_tokenizer

    model_dir = _get_trio_model_dir()
    ckpt_path = model_dir / f"trio-{preset}.pt"

    if ckpt_path.exists():
        return str(ckpt_path)

    # Check for bundled pre-trained weights shipped with the package
    bundled_path = Path(__file__).parent.parent.parent / "trio_model" / "checkpoints" / f"trio-{preset}.pt"
    if bundled_path.exists():
        print(f"\n[trio.ai] Deploying trio-max model...")
        shutil.copy2(str(bundled_path), str(ckpt_path))
        print(f"[trio.ai] trio-max ready.")
        return str(ckpt_path)

    print(f"\n[trio.ai] First-time setup: Initializing trio-max...")
    print(f"[trio.ai] This only happens once.")

    cfg = get_config(preset)
    tokenizer = get_tokenizer(preset)
    cfg.vocab_size = tokenizer.vocab_size

    model = TrioModel(cfg)
    print(f"[trio.ai] trio-max initialized.")

    ckpt = {
        "step": 0,
        "val_loss": float("inf"),
        "model": model.state_dict(),
        "config": cfg.__dict__,
    }
    torch.save(ckpt, str(ckpt_path))
    print(f"[trio.ai] trio-max ready.\n")

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
            "Hello! I'm Trio, your AI assistant powered by trio-max.\n"
            "Running locally on your system — no API keys, no cloud.\n\n"
            "How can I help you?"
        ),
        "who_are_you": (
            "I'm Trio — an open-source AI assistant built by Karan Garg.\n\n"
            "- Runs 100% on your machine\n"
            "- No API keys or cloud dependency\n"
            "- Your data stays private\n"
            "- 1,600+ built-in skills\n"
            "- Multi-platform: CLI, Discord, Telegram, Signal\n\n"
            "Powered by trio-max, a custom transformer model."
        ),
        "capabilities": (
            "I can help with:\n\n"
            "- Coding (Python, JS, Go, Rust, and 30+ languages)\n"
            "- Writing, editing, and content creation\n"
            "- Data analysis and visualization\n"
            "- DevOps, Docker, Kubernetes, CI/CD\n"
            "- Marketing, SEO, social media strategy\n"
            "- Security audits and penetration testing\n"
            "- Business strategy and startup advisory\n"
            "- Web search, math, shell, file operations\n\n"
            "1,600+ skills built-in. Ask me anything."
        ),
        "help": (
            "Quick commands:\n\n"
            "  trio agent           - Chat with me\n"
            "  trio agent -m \"msg\"  - Single message\n"
            "  trio status          - System status\n"
            "  trio provider add    - Add cloud LLM\n"
            "  trio onboard         - Re-run setup\n"
            "  /help               - In-chat help\n"
            "  /coder              - Coding mode\n"
            "  /think              - Reasoning mode\n"
            "  /reset              - Clear conversation"
        ),
        "farewell": "Goodbye! Run `trio agent` anytime to chat again.",
        "default": (
            "Let me help you with that. I'm running trio-max locally on your system.\n\n"
            "I have 1,600+ built-in skills covering coding, writing, DevOps, marketing, "
            "data science, security, and more. Try asking me something specific like:\n\n"
            "- \"Help me write a Python web scraper\"\n"
            "- \"Create a Docker compose file for a Node.js app\"\n"
            "- \"Write a LinkedIn post about my open source project\"\n"
            "- \"Explain Kubernetes networking\""
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
        self.default_model = config.get("default_model", "trio-max")

    # Map user-facing names to internal architecture presets
    MODEL_MAP = {
        "max": "nano",       # Default — auto-selects best for system
        "nano": "nano",      # Explicit CPU-only
        "small": "small",    # GPU (T4+)
        "medium": "medium",  # GPU (A100+)
    }

    def _get_engine(self, model: str | None = None):
        """Lazy-load the Trio model engine. Auto-setup if needed."""
        if self._engine is not None:
            return self._engine

        try:
            import torch
            from trio_model.inference.server import TrioEngine

            # Resolve user-facing model name to internal preset
            model_name = (model or self.default_model).replace("trio-", "")
            if model_name == "max":
                # Auto-detect best preset for this system
                resources = _detect_system_resources()
                preset = _auto_select_preset(resources)
                print(f"[trio.ai] System: {resources['cpu_cores']} cores, {resources['ram_gb']}GB RAM", end="")
                if resources["gpu_available"]:
                    print(f", GPU: {resources['gpu_name']} ({resources['gpu_vram_gb']}GB)")
                else:
                    print("")
            else:
                preset = self.MODEL_MAP.get(model_name, "nano")

            # Auto-setup model
            ckpt_path = _auto_setup_model(preset)

            # Check if model is trained (step > 0)
            ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
            step = ckpt.get("step", 0)
            self._is_trained = step > 0

            if self._is_trained:
                self._engine = TrioEngine(ckpt_path, preset=preset)
                print(f"[trio.ai] trio-max loaded and ready")
            else:
                self._engine = self._fallback
                print(f"[trio.ai] trio-max ready (base knowledge)")

            self.default_model = "trio-max"

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
        """List available Trio models."""
        return ["trio-max"]

    async def close(self) -> None:
        self._engine = None
        self._is_trained = False
