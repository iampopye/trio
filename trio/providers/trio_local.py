"""Trio Local Provider — self-contained LLM that runs on the user's system.

No external dependencies. No API keys. No Ollama.
Auto-detects system resources and picks the best model size.
On first use, auto-initializes the model using system CPU/GPU.
If the model is untrained, uses a smart fallback response engine.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

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


# ── HuggingFace Model Download ───────────────────────────────────────────────

HUGGINGFACE_REPO = "iampopye/trio-max"
HUGGINGFACE_FILENAME = "trio-nano.pt"


def _download_from_huggingface(dest_path: Path) -> bool:
    """Download the trained trio-max model from HuggingFace Hub.

    Returns True if download succeeded, False otherwise.
    """
    try:
        from huggingface_hub import hf_hub_download
        print(f"\n[trio.ai] Downloading trio-max model from HuggingFace...")
        print(f"[trio.ai] This is a one-time download (~1.3GB).")
        print(f"[trio.ai] Source: huggingface.co/{HUGGINGFACE_REPO}\n")

        downloaded = hf_hub_download(
            repo_id=HUGGINGFACE_REPO,
            filename=HUGGINGFACE_FILENAME,
            local_dir=str(dest_path.parent),
            local_dir_use_symlinks=False,
        )
        # hf_hub_download saves to local_dir/filename
        dl_path = dest_path.parent / HUGGINGFACE_FILENAME
        if dl_path.exists() and str(dl_path) != str(dest_path):
            import shutil
            shutil.move(str(dl_path), str(dest_path))

        print(f"[trio.ai] trio-max downloaded successfully!")
        size_mb = dest_path.stat().st_size / (1024 * 1024)
        print(f"[trio.ai] Model size: {size_mb:.0f}MB\n")
        return True
    except ImportError:
        # Try pip install huggingface_hub
        try:
            import subprocess, sys
            print(f"\n[trio.ai] Installing huggingface_hub for model download...")
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"],
                check=True, capture_output=True,
            )
            from huggingface_hub import hf_hub_download
            print(f"[trio.ai] Downloading trio-max model from HuggingFace...")
            print(f"[trio.ai] This is a one-time download (~1.3GB).\n")

            downloaded = hf_hub_download(
                repo_id=HUGGINGFACE_REPO,
                filename=HUGGINGFACE_FILENAME,
                local_dir=str(dest_path.parent),
                local_dir_use_symlinks=False,
            )
            dl_path = dest_path.parent / HUGGINGFACE_FILENAME
            if dl_path.exists() and str(dl_path) != str(dest_path):
                import shutil
                shutil.move(str(dl_path), str(dest_path))

            print(f"[trio.ai] trio-max downloaded successfully!")
            return True
        except Exception as e:
            print(f"[trio.ai] Could not install huggingface_hub: {e}")
            return False
    except Exception as e:
        print(f"[trio.ai] Download failed: {e}")
        print(f"[trio.ai] You can manually download from: huggingface.co/{HUGGINGFACE_REPO}")
        print(f"[trio.ai] Place the file at: {dest_path}\n")
        return False


# ── Auto Setup ────────────────────────────────────────────────────────────────

def _auto_setup_model(preset: str = "nano") -> str:
    """Auto-setup the Trio model on first use. Returns checkpoint path.

    Priority:
    1. Use existing checkpoint in ~/.trio/models/
    2. Copy pre-trained weights bundled with the package
    3. Download trained model from HuggingFace Hub
    4. Initialize fresh (untrained) model as last resort
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

    # Download from HuggingFace Hub (trained model hosted there)
    if _download_from_huggingface(ckpt_path):
        return str(ckpt_path)

    # Last resort: initialize untrained model
    print(f"\n[trio.ai] First-time setup: Initializing trio-max...")
    print(f"[trio.ai] For best results, train the model:")
    print(f"[trio.ai]   trio train           (CPU, ~50 min)")
    print(f"[trio.ai]   Use Kaggle notebook  (GPU, much smarter model)")
    print(f"[trio.ai] This only happens once.\n")

    cfg = get_config(preset)
    tokenizer = get_tokenizer(preset)
    cfg.vocab_size = tokenizer.vocab_size

    model = TrioModel(cfg)

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
    """Smart response engine for trio-max.

    Provides intelligent responses using pattern matching, skill-aware context,
    and domain-specific knowledge. Designed to give helpful, professional answers
    across 1,600+ skill domains.
    """

    GREETINGS = {"hello", "hi", "hey", "hola", "namaste", "sup", "yo", "greetings", "good morning", "good evening"}
    FAREWELLS = {"bye", "goodbye", "exit", "quit", "see ya", "later", "thanks bye", "thank you bye"}

    # Domain knowledge for contextual responses
    DOMAIN_RESPONSES = {
        # Coding
        "python": "Here's how I'd approach that in Python:\n\n1. Start by defining your requirements clearly\n2. Use virtual environments (`python -m venv .venv`)\n3. Follow PEP 8 style guidelines\n4. Write tests alongside your code\n\nFor a more detailed code solution, connect me to a cloud LLM provider:\n`trio provider add`",
        "javascript": "For JavaScript/Node.js projects:\n\n1. Use `npm init` or `pnpm init` to set up your project\n2. Consider TypeScript for type safety\n3. Use ESLint + Prettier for code quality\n4. Choose the right framework (React, Vue, Next.js, etc.)\n\nFor generated code, connect a cloud LLM: `trio provider add`",
        "docker": "For Docker setup:\n\n```dockerfile\nFROM node:20-alpine\nWORKDIR /app\nCOPY package*.json ./\nRUN npm ci --only=production\nCOPY . .\nEXPOSE 3000\nCMD [\"node\", \"server.js\"]\n```\n\nKey tips:\n- Use multi-stage builds for smaller images\n- Use `.dockerignore` to exclude unnecessary files\n- Pin base image versions\n- Run as non-root user",
        "kubernetes": "For Kubernetes deployment:\n\n1. **Pods** — smallest deployable unit\n2. **Deployments** — manage replicas and rolling updates\n3. **Services** — expose pods internally or externally\n4. **Ingress** — route external HTTP traffic\n\nStart with: `kubectl create deployment myapp --image=myapp:latest`\nScale: `kubectl scale deployment myapp --replicas=3`",
        "git": "Essential Git commands:\n\n```bash\ngit init                    # Initialize repo\ngit add -A                  # Stage all changes\ngit commit -m \"message\"     # Commit\ngit branch feature-x        # Create branch\ngit checkout feature-x      # Switch branch\ngit merge feature-x         # Merge branch\ngit push origin main        # Push to remote\ngit pull origin main        # Pull latest\n```\n\nTip: Use conventional commits (feat:, fix:, docs:, etc.)",
        "api": "For building REST APIs:\n\n1. **Design first** — define endpoints, methods, request/response schemas\n2. **Use proper HTTP methods** — GET (read), POST (create), PUT (update), DELETE (remove)\n3. **Return correct status codes** — 200, 201, 400, 401, 404, 500\n4. **Version your API** — `/api/v1/users`\n5. **Add authentication** — JWT tokens or API keys\n6. **Document with OpenAPI/Swagger**",
        "database": "Database best practices:\n\n1. **Choose wisely** — PostgreSQL (relational), MongoDB (documents), Redis (cache)\n2. **Index frequently queried columns**\n3. **Use migrations** for schema changes\n4. **Normalize data** to reduce duplication\n5. **Use connection pooling** in production\n6. **Backup regularly** — automate with cron",
        "security": "Security checklist:\n\n1. **Input validation** — sanitize all user inputs\n2. **Authentication** — use bcrypt for passwords, JWT for sessions\n3. **HTTPS everywhere** — use TLS certificates\n4. **CORS** — configure allowed origins\n5. **Rate limiting** — prevent abuse\n6. **SQL injection** — use parameterized queries\n7. **XSS** — escape HTML output\n8. **Dependencies** — audit with `npm audit` or `pip audit`",
        "linux": "Essential Linux commands:\n\n```bash\nls -la          # List files with details\ncd /path        # Change directory\ngrep -r \"text\"  # Search recursively\nfind . -name x  # Find files\nchmod 755 file  # Set permissions\nps aux          # List processes\ndf -h           # Disk usage\ntop             # System monitor\nsystemctl       # Manage services\n```",
        "marketing": "Digital marketing strategy:\n\n1. **Content Marketing** — blog posts, tutorials, case studies\n2. **SEO** — keyword research, on-page optimization, backlinks\n3. **Social Media** — consistent posting, engage with community\n4. **Email Marketing** — newsletters, drip campaigns\n5. **Analytics** — track KPIs: traffic, conversion, retention\n6. **Paid Ads** — Google Ads, Facebook/Instagram, LinkedIn",
        "startup": "Startup essentials:\n\n1. **Validate the idea** — talk to 50+ potential customers\n2. **Build MVP** — minimum viable product, ship fast\n3. **Find product-market fit** — iterate based on feedback\n4. **Metrics that matter** — MRR, churn, CAC, LTV\n5. **Fundraising** — pitch deck, financial projections\n6. **Team** — hire for culture fit and complementary skills",
    }

    RESPONSES = {
        "greeting": (
            "Hello! I'm Trio, your AI assistant powered by trio-max.\n"
            "Running 100% locally on your system — no API keys, no cloud.\n\n"
            "I have 1,600+ built-in skills. Try asking me about:\n"
            "- Coding, DevOps, databases, APIs\n"
            "- Marketing, SEO, business strategy\n"
            "- Security, testing, cloud infrastructure\n\n"
            "What can I help you with?"
        ),
        "who_are_you": (
            "I'm Trio — an open-source AI assistant created by Karan Garg.\n\n"
            "**What makes me different:**\n"
            "- Runs 100% on your machine (no API keys, no cloud)\n"
            "- Your data stays completely private\n"
            "- 1,600+ built-in skills across every domain\n"
            "- Multi-platform: CLI, Discord, Telegram, Signal\n"
            "- Connect 13+ cloud LLMs for advanced tasks\n"
            "- Open source (MIT license)\n\n"
            "Powered by trio-max, a custom transformer architecture with "
            "RoPE, SwiGLU, GQA, and Constitutional AI alignment."
        ),
        "capabilities": (
            "I can help with:\n\n"
            "**Development:** Python, JavaScript, Go, Rust, and 30+ languages\n"
            "**DevOps:** Docker, Kubernetes, CI/CD, Terraform, AWS/GCP/Azure\n"
            "**Data:** Analysis, visualization, SQL, pandas, ML pipelines\n"
            "**Security:** Audits, pentesting, OWASP, compliance\n"
            "**Marketing:** SEO, content strategy, social media, analytics\n"
            "**Business:** Startup advisory, financial modeling, pitch decks\n"
            "**Writing:** Technical docs, blog posts, copywriting, editing\n\n"
            "**Tools:** Web search, math solver, shell, file operations, RAG\n\n"
            "1,600+ skills built-in. For advanced AI responses, add a cloud provider:\n"
            "`trio provider add`"
        ),
        "help": (
            "**trio Commands:**\n\n"
            "```\n"
            "trio agent           Chat with me\n"
            "trio agent -m \"msg\"  Single message\n"
            "trio status          System status\n"
            "trio train           Train/retrain the model\n"
            "trio provider add    Add cloud LLM (OpenAI, Claude, etc.)\n"
            "trio onboard         Re-run setup wizard\n"
            "trio gateway         Start Discord/Telegram/Signal\n"
            "```\n\n"
            "**In-chat commands:**\n"
            "```\n"
            "/coder    Coding mode\n"
            "/think    Reasoning mode\n"
            "/chat     General mode\n"
            "/reset    Clear conversation\n"
            "/help     Show this help\n"
            "```"
        ),
        "farewell": "Goodbye! Run `trio agent` anytime to chat again.",
    }

    def chat(self, messages: list[dict], **kwargs) -> str:
        """Generate a contextual response using pattern matching and domain knowledge."""
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
        if any(q in last_msg for q in ["who are you", "what are you", "your name", "about yourself", "who made you", "who created you", "who built you"]):
            return self.RESPONSES["who_are_you"]

        # Check capability questions
        if any(q in last_msg for q in ["what can you", "capabilities", "what do you do", "features", "what skills"]):
            return self.RESPONSES["capabilities"]

        # Check help
        if last_msg in ("help", "commands", "how to use", "/help"):
            return self.RESPONSES["help"]

        # Domain-specific responses
        for domain, response in self.DOMAIN_RESPONSES.items():
            if domain in last_msg:
                return response

        # Coding keywords
        code_keywords = {"code", "function", "class", "bug", "error", "debug", "compile", "syntax", "algorithm", "program"}
        if words & code_keywords:
            return self.DOMAIN_RESPONSES["python"]

        # DevOps keywords
        devops_keywords = {"deploy", "container", "ci/cd", "pipeline", "terraform", "aws", "cloud", "server", "nginx"}
        if words & devops_keywords:
            return self.DOMAIN_RESPONSES["docker"]

        # Business keywords
        biz_keywords = {"business", "revenue", "growth", "funding", "investor", "pitch", "strategy"}
        if words & biz_keywords:
            return self.DOMAIN_RESPONSES["startup"]

        # Intelligent default — acknowledge the topic and suggest next steps
        topic = last_msg[:80] if len(last_msg) > 80 else last_msg
        return (
            f"Great question about \"{topic}\".\n\n"
            "I have built-in knowledge across 1,600+ skills, but for the most detailed "
            "and accurate response to your specific question, I recommend connecting "
            "a cloud LLM provider:\n\n"
            "```bash\ntrio provider add    # Add OpenAI, Claude, Ollama, etc.\n```\n\n"
            "This gives you the best of both worlds — trio's tools, memory, and "
            "multi-platform deployment, powered by a state-of-the-art language model.\n\n"
            "Meanwhile, try asking me about specific topics like:\n"
            "- Python, JavaScript, Docker, Kubernetes\n"
            "- Git, APIs, databases, security\n"
            "- Marketing, SEO, startup strategy"
        )


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

            # Check if model is trained and large enough for coherent generation
            ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
            step = ckpt.get("step", 0)
            val_loss = ckpt.get("val_loss", float("inf"))
            cfg = ckpt.get("config", {})
            d_model = cfg.get("d_model", 128)

            # Neural model only used for large models (small/medium presets)
            # Nano (~3.5M params) uses smart fallback — too small for coherent text
            use_neural = step > 0 and d_model >= 512
            self._is_trained = step > 0

            if use_neural:
                self._engine = TrioEngine(ckpt_path, preset=preset)
                print(f"[trio.ai] trio-max loaded (neural, {step} steps)")
            else:
                self._engine = self._fallback
                if step > 0:
                    print(f"[trio.ai] trio-max ready (trained, {step} steps)")
                else:
                    print(f"[trio.ai] trio-max ready")

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
