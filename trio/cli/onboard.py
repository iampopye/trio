"""trio onboard -- interactive 6-step setup wizard."""

import json
import os
import platform
import re
import shutil
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt, Confirm
from rich.table import Table
from rich.text import Text
from rich.columns import Columns
from rich import box

from trio.core.config import (
    get_trio_dir, get_config_path, get_workspace_dir,
    get_memory_dir, get_sessions_dir, get_skills_dir,
    get_notes_dir, get_plugins_dir,
    DEFAULT_CONFIG, save_config,
)

console = Console()

# ── Skill category definitions ───────────────────────────────────────────────
# Each category maps to keyword patterns matched against skill names/descriptions.
# The "display" fields are used in the wizard UI.

SKILL_CATEGORIES = {
    "coding": {
        "icon": "[>]",
        "label": "Coding & DevOps",
        "keywords": [
            "code", "coding", "develop", "debug", "git", "docker", "devops",
            "ci/cd", "deploy", "api", "backend", "engineer", "refactor",
            "test", "build", "compiler", "ide", "sdk", "framework", "library",
            "package", "npm", "pip", "rust", "python", "javascript",
            "typescript", "java", "golang", "ruby", "swift", "kotlin",
            "flutter", "react", "vue", "angular", "node", "django", "rails",
            "laravel", "nextjs", "svelte", "database", "sql", "postgres",
            "mongo", "redis", "kubernetes", "terraform", "ansible", "aws",
            "azure", "gcp", "cloud", "microservice", "agile", "scrum",
            "architecture", "lint", "algorithm", "clean code", "solid",
        ],
        "file_categories": ["development", "engineering", "code", "code-quality",
                            "backend", "devops", "framework", "api-integration",
                            "testing", "test-automation", "reliability",
                            "development-and-testing", "database-processing"],
    },
    "marketing": {
        "icon": "[M]",
        "label": "Marketing & Content",
        "keywords": [
            "marketing", "seo", "content", "social media", "brand", "ads",
            "campaign", "copywriting", "copy", "email marketing", "funnel",
            "lead", "growth", "analytics", "conversion", "audience",
            "influencer", "blog", "newsletter", "adwords", "facebook ads",
            "google ads", "tiktok", "instagram", "linkedin", "twitter",
        ],
        "file_categories": ["marketing", "content", "media"],
    },
    "security": {
        "icon": "[S]",
        "label": "Security & Pentesting",
        "keywords": [
            "security", "pentest", "hack", "exploit", "vulnerab", "audit",
            "owasp", "threat", "malware", "forensic", "incident", "firewall",
            "encrypt", "cipher", "ctf", "red team", "blue team", "infosec",
            "cybersec", "hardening", "penetration", "xss", "injection",
            "privilege escalation", "reverse engineer",
        ],
        "file_categories": ["security"],
    },
    "finance": {
        "icon": "[$]",
        "label": "Finance & Business",
        "keywords": [
            "finance", "invest", "trading", "stock", "crypto", "blockchain",
            "defi", "accounting", "budget", "revenue", "profit", "tax",
            "bank", "payment", "fintech", "valuation", "portfolio", "startup",
            "business", "entrepreneur", "saas", "pricing", "strategy",
            "consulting", "executive", "c-level", "ceo", "cto", "cfo",
        ],
        "file_categories": ["finance", "business", "c-level"],
    },
    "data_science": {
        "icon": "[D]",
        "label": "Data Science & AI",
        "keywords": [
            "data science", "machine learn", "deep learn", "neural", "nlp",
            "computer vision", "tensor", "pytorch", "sklearn", "pandas",
            "numpy", "statistics", "regression", "classification",
            "clustering", "model train", "dataset", "feature engineer",
            "etl", "pipeline", "data analy", "llm", "transformer", "gpt",
            "rag", "embedding", "vector", "hugging", "fine-tun",
        ],
        "file_categories": ["data-ai", "data", "data-engineering", "ai-research",
                            "ai-agents", "ai-testing"],
    },
    "creative": {
        "icon": "[C]",
        "label": "Creative Writing & Design",
        "keywords": [
            "creative", "writing", "story", "novel", "fiction", "poetry",
            "poem", "script", "screenwrite", "narrative", "character",
            "dialogue", "worldbuild", "fantasy", "design", "art",
            "illustration", "music", "compose", "lyric", "video", "image",
            "photo", "graphic", "visual", "animation", "3d",
        ],
        "file_categories": ["graphics-processing", "presentation-processing"],
    },
    "sysadmin": {
        "icon": "[#]",
        "label": "System Administration",
        "keywords": [
            "system admin", "sysadmin", "linux", "unix", "windows", "server",
            "network", "dns", "ssl", "nginx", "apache", "monitor", "backup",
            "disaster", "shell", "bash", "powershell", "cron", "systemd",
            "virtualization", "vmware", "proxmox", "active directory",
            "ldap", "dhcp", "tcp", "ip", "routing", "vpn",
        ],
        "file_categories": ["automation", "productivity"],
    },
    "education": {
        "icon": "[E]",
        "label": "Education & Research",
        "keywords": [
            "education", "teach", "learn", "tutor", "course", "curriculum",
            "research", "academic", "paper", "thesis", "citation", "study",
            "exam", "quiz", "lecture", "student", "scholar", "journal",
            "peer review", "bibliography", "abstract", "methodology",
        ],
        "file_categories": ["memory", "planning"],
    },
    "web": {
        "icon": "[W]",
        "label": "Web Development",
        "keywords": [
            "web", "html", "css", "frontend", "responsive", "browser",
            "dom", "webpack", "vite", "tailwind", "bootstrap", "sass",
            "animation", "ui", "ux", "figma", "accessibility", "a11y",
            "wordpress", "shopify", "wix", "landing page", "e-commerce",
            "ecommerce", "nextjs", "gatsby", "jamstack",
        ],
        "file_categories": ["frontend", "spreadsheet-processing",
                            "document-processing"],
    },
}

# ── Tool definitions for Step 4 ─────────────────────────────────────────────

AVAILABLE_TOOLS = [
    ("web_search",  "Web Search",       "Search the internet for information",    True),
    ("shell",       "Shell",            "Run terminal commands",                   True),
    ("file_ops",    "File Operations",  "Read, write, and manage files",          True),
    ("browser",     "Browser",          "Web automation via Playwright",          True),
    ("url_reader",  "URL Reader",       "Fetch and parse web pages",              True),
    ("email",       "Email",            "Send and receive email",                 False),
    ("calendar",    "Calendar",         "Manage calendar events",                 False),
    ("notes",       "Notes",            "Persistent note-taking",                 False),
    ("screenshot",  "Screenshot",       "Capture screen content",                 False),
    ("math_solver", "Math",             "Advanced mathematical calculations",     False),
]


# ── Utility helpers ──────────────────────────────────────────────────────────

def _friendly_path(p: Path) -> str:
    """Show ~/.trio/... instead of full absolute path."""
    try:
        rel = p.relative_to(Path.home())
        return f"~/{rel.as_posix()}"
    except ValueError:
        return str(p)


def _detect_ollama() -> dict | None:
    """Auto-detect running Ollama instance and available models."""
    try:
        import urllib.request
        import json as _json
        req = urllib.request.Request("http://localhost:11434/api/tags", method="GET")
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = _json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            return {"url": "http://localhost:11434", "models": models}
    except Exception:
        return None


def _pick_best_model(models: list[str]) -> str:
    """Pick the best available model from Ollama."""
    preferred = [
        "llama3.1:8b", "llama3.2:3b", "llama3.2:1b", "llama3:8b",
        "mistral:7b", "gemma2:9b", "qwen2.5:7b", "phi3:3.8b",
    ]
    for p in preferred:
        if p in models:
            return p
    return models[0] if models else "llama3.2:1b"


def _setup_provider_manual(config: dict):
    """Manual provider selection."""
    console.print("\n  [bold]Select provider:[/bold]")
    provider = Prompt.ask(
        "  Provider",
        choices=["ollama", "openai", "anthropic", "gemini", "groq", "openrouter", "deepseek"],
        default="ollama",
    )

    if provider == "ollama":
        base_url = Prompt.ask("  Ollama URL", default="http://localhost:11434")
        model = Prompt.ask("  Model", default="llama3.2:1b")
        config["providers"]["ollama"] = {
            "base_url": base_url,
            "default_model": model,
        }
        config["agents"]["defaults"]["provider"] = "ollama"
        config["agents"]["defaults"]["model"] = model
    else:
        api_key = Prompt.ask(f"  {provider} API key")
        defaults = {
            "openai": "gpt-4o",
            "anthropic": "claude-sonnet-4-20250514",
            "gemini": "gemini-2.0-flash",
            "groq": "llama-3.1-8b-instant",
            "openrouter": "meta-llama/llama-3.1-8b-instruct",
            "deepseek": "deepseek-chat",
        }
        model = Prompt.ask("  Model", default=defaults.get(provider, ""))
        config["providers"][provider] = {
            "apiKey": api_key,
            "default_model": model,
        }
        config["agents"]["defaults"]["provider"] = provider
        config["agents"]["defaults"]["model"] = model

    console.print(f"  [green]\u2713 Provider: {provider} ({config['agents']['defaults']['model']})[/green]")


def _setup_local_gguf(config: dict):
    """Setup local GGUF provider (native inference, no Ollama)."""
    from trio.providers.local import _find_gguf_model, _list_gguf_models

    console.print("\n  [bold]Local GGUF Inference[/bold]  [dim](llama-cpp-python)[/dim]\n")

    # Check if llama-cpp-python is installed
    try:
        import llama_cpp
        console.print(f"  [green]\u2713[/green] llama-cpp-python found (v{llama_cpp.__version__})")
    except ImportError:
        console.print("  [yellow]! llama-cpp-python is not installed.[/yellow]")
        console.print("    Install with: [cyan]pip install llama-cpp-python[/cyan]")
        console.print("    For GPU:      [cyan]CMAKE_ARGS=\"-DGGML_CUDA=on\" pip install llama-cpp-python[/cyan]")
        console.print()

    # List available GGUF models
    available = _list_gguf_models()
    if available:
        console.print(f"\n  Found {len(available)} GGUF model(s):")
        for idx, name in enumerate(available, 1):
            console.print(f"    [cyan]{idx}[/cyan]. {name}")
        console.print()

    # Choose model
    model_choices = ["trio-max", "trio-nano", "custom"]
    console.print("  Which model to use?")
    console.print("    [cyan]1[/cyan]  trio-max   [dim](recommended)[/dim]")
    console.print("    [cyan]2[/cyan]  trio-nano  [dim](smaller, faster)[/dim]")
    console.print("    [cyan]3[/cyan]  Custom path to a .gguf file")
    console.print()

    model_choice = Prompt.ask("  Model", choices=["1", "2", "3"], default="2" if available else "3")

    model_name = ""
    model_path = ""

    if model_choice == "1":
        model_name = "trio-max"
        detected = _find_gguf_model(model_name="trio-max")
        if detected:
            model_path = detected
            console.print(f"  [green]\u2713[/green] Found: {detected}")
        else:
            console.print("  [yellow]! trio-max GGUF not found. Place trio-max-q4_k_m.gguf in ~/.trio/models/[/yellow]")
    elif model_choice == "2":
        model_name = "trio-nano"
        detected = _find_gguf_model(model_name="trio-nano")
        if detected:
            model_path = detected
            console.print(f"  [green]\u2713[/green] Found: {detected}")
        else:
            console.print("  [yellow]! trio-nano GGUF not found. Place trio-nano-q4_k_m.gguf in ~/.trio/models/[/yellow]")
    else:
        model_path = Prompt.ask("  Path to .gguf file")
        if model_path and os.path.isfile(model_path):
            model_name = os.path.basename(model_path).replace(".gguf", "")
            console.print(f"  [green]\u2713[/green] Found: {model_path}")
        else:
            console.print(f"  [yellow]! File not found: {model_path}[/yellow]")
            model_name = "custom"

    # GPU layers
    console.print()
    console.print("  GPU offloading:")
    console.print("    [cyan]-1[/cyan]  All layers on GPU  [dim](recommended if you have a GPU)[/dim]")
    console.print("    [cyan] 0[/cyan]  CPU only")
    console.print("    [cyan] N[/cyan]  Offload N layers to GPU")
    n_gpu = Prompt.ask("  GPU layers", default="-1")
    try:
        n_gpu_layers = int(n_gpu)
    except ValueError:
        n_gpu_layers = -1

    # Context size
    n_ctx = Prompt.ask("  Context size", default="8192")
    try:
        n_ctx_val = int(n_ctx)
    except ValueError:
        n_ctx_val = 8192

    # Save config
    config["providers"]["local"] = {
        "model_path": model_path,
        "default_model": model_name,
        "n_ctx": n_ctx_val,
        "n_gpu_layers": n_gpu_layers,
        "chat_format": "chatml",
    }
    config["agents"]["defaults"]["provider"] = "local"
    config["agents"]["defaults"]["model"] = model_name

    console.print(f"\n  [green]\u2713 Provider: local GGUF ({model_name})[/green]")


def _setup_channels(config: dict):
    """Interactive channel setup."""
    channels = [
        ("Discord",            "discord",      ["token"]),
        ("Telegram",           "telegram",     ["token"]),
        ("Slack",              "slack",        ["bot_token", "app_token"]),
        ("WhatsApp",           "whatsapp",     ["phone_number_id", "access_token"]),
        ("Teams",              "teams",        ["app_id", "app_password"]),
        ("Google Chat",        "google_chat",  ["service_account_file"]),
        ("Signal",             "signal",       ["phone"]),
        ("Matrix/Element",     "matrix",       ["homeserver_url", "user_id", "access_token"]),
        ("SMS (Twilio)",       "sms",          ["account_sid", "auth_token", "phone_number"]),
        ("Instagram DM",       "instagram",    ["page_id", "access_token"]),
        ("Facebook Messenger", "messenger",    ["page_id", "access_token"]),
        ("LINE",               "line",         ["channel_access_token", "channel_secret"]),
        ("Reddit",             "reddit",       ["client_id", "client_secret", "username", "password"]),
        ("Email (IMAP/SMTP)",  "email",        ["imap_host", "smtp_host", "username", "password"]),
    ]

    if platform.system() == "Darwin":
        channels.append(("iMessage", "imessage", []))

    for display_name, key, fields in channels:
        if Confirm.ask(f"  Enable {display_name}?", default=False):
            config["channels"][key]["enabled"] = True
            for field in fields:
                value = Prompt.ask(f"    {field}")
                config["channels"][key][field] = value


# ── Skill scanning ───────────────────────────────────────────────────────────

def _scan_skill_categories() -> dict[str, int]:
    """Scan builtin skills directory and count files per wizard category.

    Each skill file is read (first 500 bytes) for name, description, category,
    and tags.  A file is assigned to the *first* wizard category whose keywords
    or file_categories match.  Unmatched files go to a virtual 'other' bucket.
    """
    builtin_dir = Path(__file__).resolve().parent.parent / "skills" / "builtin"
    counts: dict[str, int] = {k: 0 for k in SKILL_CATEGORIES}
    counts["other"] = 0

    if not builtin_dir.is_dir():
        return counts

    for md_file in builtin_dir.glob("*.md"):
        try:
            header = md_file.read_text(encoding="utf-8", errors="ignore")[:600].lower()
        except Exception:
            continue

        matched = False

        # --- Check file_category field first (fast path) ---
        cat_match = re.search(r"category:\s*[\"']?([a-z0-9_-]+)", header)
        file_cat = cat_match.group(1) if cat_match else ""

        for key, meta in SKILL_CATEGORIES.items():
            if file_cat and file_cat in meta.get("file_categories", []):
                counts[key] += 1
                matched = True
                break

        if matched:
            continue

        # --- Keyword match on name + description ---
        for key, meta in SKILL_CATEGORIES.items():
            for kw in meta["keywords"]:
                if kw in header:
                    counts[key] += 1
                    matched = True
                    break
            if matched:
                break

        if not matched:
            counts["other"] += 1

    return counts


def _get_total_skill_count() -> int:
    """Return total number of builtin .md skill files."""
    builtin_dir = Path(__file__).resolve().parent.parent / "skills" / "builtin"
    if not builtin_dir.is_dir():
        return 0
    return sum(1 for _ in builtin_dir.glob("*.md"))


# ── System check helpers ─────────────────────────────────────────────────────

def _get_ram_gb() -> str:
    """Detect total system RAM in GB (uses psutil if available, fallback)."""
    try:
        import psutil
        total = psutil.virtual_memory().total
        return f"{total / (1024 ** 3):.1f} GB"
    except ImportError:
        pass

    # Fallback: platform-specific
    if platform.system() == "Windows":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            c_ulong = ctypes.c_ulonglong
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", c_ulong),
                    ("ullAvailPhys", c_ulong),
                    ("ullTotalPageFile", c_ulong),
                    ("ullAvailPageFile", c_ulong),
                    ("ullTotalVirtual", c_ulong),
                    ("ullAvailVirtual", c_ulong),
                    ("ullAvailExtendedVirtual", c_ulong),
                ]
            mem = MEMORYSTATUSEX()
            mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
            return f"{mem.ullTotalPhys / (1024 ** 3):.1f} GB"
        except Exception:
            pass
    elif platform.system() == "Linux":
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        kb = int(line.split()[1])
                        return f"{kb / (1024 ** 2):.1f} GB"
        except Exception:
            pass
    elif platform.system() == "Darwin":
        try:
            import subprocess
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip()
            return f"{int(out) / (1024 ** 3):.1f} GB"
        except Exception:
            pass

    return "unknown"


def _detect_gpu() -> str:
    """Attempt to detect GPU (NVIDIA via nvidia-smi, then fallback)."""
    # Try NVIDIA
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        try:
            import subprocess
            out = subprocess.check_output(
                [nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                text=True, timeout=5,
            ).strip()
            if out:
                parts = out.split(",")
                name = parts[0].strip()
                mem = parts[1].strip() if len(parts) > 1 else "?"
                return f"{name} ({mem} MB)"
        except Exception:
            pass

    # Try ROCm (AMD)
    rocm = shutil.which("rocm-smi")
    if rocm:
        return "AMD ROCm GPU detected"

    # Check for Apple Silicon
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        return "Apple Silicon (unified memory)"

    return "none detected"


# ── Step functions ───────────────────────────────────────────────────────────

def _step_system_check() -> None:
    """Step 1/6: System Check."""
    console.print()
    console.print(Panel(
        "[bold white]Step 1/6[/bold white]  [bold cyan]System Check[/bold cyan]",
        border_style="cyan", box=box.HEAVY,
    ))

    checks = []

    # Python version
    py_ver = platform.python_version()
    py_ok = sys.version_info >= (3, 10)
    mark = "[green]\u2713[/green]" if py_ok else "[yellow]![/yellow]"
    detail = f"Python {py_ver}"
    if not py_ok:
        detail += "  [yellow](3.10+ recommended)[/yellow]"
    checks.append((mark, detail))

    # OS / Platform
    os_name = f"{platform.system()} {platform.release()}"
    checks.append(("[green]\u2713[/green]", f"Platform: {os_name} ({platform.machine()})"))

    # RAM
    ram = _get_ram_gb()
    if ram != "unknown":
        ram_ok = True
        try:
            ram_val = float(ram.replace(" GB", ""))
            ram_ok = ram_val >= 4.0
        except ValueError:
            pass
        mark = "[green]\u2713[/green]" if ram_ok else "[yellow]![/yellow]"
        checks.append((mark, f"RAM: {ram}"))
    else:
        checks.append(("[dim]-[/dim]", "RAM: could not detect"))

    # GPU
    gpu = _detect_gpu()
    if "none" in gpu.lower():
        checks.append(("[dim]-[/dim]", f"GPU: {gpu}  [dim](CPU inference will be used)[/dim]"))
    else:
        checks.append(("[green]\u2713[/green]", f"GPU: {gpu}"))

    # Ollama
    ollama_info = _detect_ollama()
    if ollama_info and ollama_info["models"]:
        n = len(ollama_info["models"])
        checks.append(("[green]\u2713[/green]", f"Ollama: running ({n} model{'s' if n != 1 else ''} available)"))
    elif ollama_info:
        checks.append(("[yellow]![/yellow]", "Ollama: running but no models installed"))
    else:
        checks.append(("[dim]-[/dim]", "Ollama: not detected  [dim](optional)[/dim]"))

    # Display
    for mark, detail in checks:
        console.print(f"  {mark}  {detail}")

    console.print()
    return ollama_info


def _check_trio_models() -> list[str]:
    """Check which trio GGUF models are available locally."""
    from pathlib import Path
    search_dirs = [
        Path.home() / ".trio" / "models",
        Path(__file__).resolve().parent.parent.parent / "models",
    ]
    found = []
    for d in search_dirs:
        if not d.is_dir():
            continue
        if (d / "trio-max-q4_k_m.gguf").is_file():
            found.append("trio-max")
        if (d / "trio-nano-q4_k_m.gguf").is_file():
            found.append("trio-nano")
    return list(dict.fromkeys(found))  # dedupe, keep order


def _step_provider(config: dict, ollama_info: dict | None) -> None:
    """Step 2/6: AI Model selection."""
    console.print(Panel(
        "[bold white]Step 2/6[/bold white]  [bold cyan]AI Model[/bold cyan]",
        border_style="cyan", box=box.HEAVY,
    ))

    # Check for local trio models
    trio_models = _check_trio_models()

    console.print("  Choose how to power your AI:\n")
    console.print("    [bold cyan]--- trio models (runs 100% on your machine) ---[/bold cyan]")

    if "trio-max" in trio_models:
        console.print("    [cyan]1[/cyan]  [bold]trio-max[/bold]  [dim](4B params, best quality)[/dim]  [green][ready][/green]")
    else:
        console.print("    [cyan]1[/cyan]  [bold]trio-max[/bold]  [dim](4B params, best quality)[/dim]  [yellow][will download ~2.5GB][/yellow]")

    if "trio-nano" in trio_models:
        console.print("    [cyan]2[/cyan]  [bold]trio-nano[/bold]  [dim](1.7B params, fast & light)[/dim]  [green][ready][/green]")
    else:
        console.print("    [cyan]2[/cyan]  [bold]trio-nano[/bold]  [dim](1.7B params, fast & light)[/dim]  [yellow][will download ~1GB][/yellow]")

    console.print()
    console.print("    [bold cyan]--- bring your own API key ---[/bold cyan]")
    console.print("    [cyan]3[/cyan]  OpenAI  [dim](GPT-4o, GPT-4-turbo)[/dim]")
    console.print("    [cyan]4[/cyan]  Anthropic  [dim](Claude Sonnet, Opus)[/dim]")
    console.print("    [cyan]5[/cyan]  Google Gemini  [dim](Gemini 2.0 Flash)[/dim]")
    console.print("    [cyan]6[/cyan]  Groq / OpenRouter / DeepSeek  [dim](any OpenAI-compatible API)[/dim]")

    if ollama_info and ollama_info.get("models"):
        console.print()
        console.print("    [bold cyan]--- detected on this machine ---[/bold cyan]")
        model_list = ", ".join(ollama_info["models"][:5])
        console.print(f"    [cyan]7[/cyan]  Ollama  [dim]({model_list})[/dim]")
        choices = ["1", "2", "3", "4", "5", "6", "7"]
    else:
        choices = ["1", "2", "3", "4", "5", "6"]

    console.print()

    # Default to trio-max if available, otherwise prompt download
    default = "1"
    choice = Prompt.ask("  Choose", choices=choices, default=default)

    if choice in ("1", "2"):
        model_name = "trio-max" if choice == "1" else "trio-nano"
        model_installed = model_name in trio_models

        if not model_installed:
            console.print(f"\n  [dim]Downloading {model_name}...[/dim]")
            console.print(f"  [dim]This is a one-time download. Grab a coffee.[/dim]\n")
            try:
                import subprocess, sys
                script = Path(__file__).resolve().parent.parent.parent / "scripts" / "setup_models.py"
                flag = "--max-only" if model_name == "trio-max" else "--nano-only"
                result = subprocess.run(
                    [sys.executable, str(script), flag],
                    timeout=600,
                )
                if result.returncode == 0:
                    console.print(f"  [green][OK][/green] {model_name} downloaded and ready!")
                else:
                    console.print(f"  [yellow]Download had issues. You can retry later: trio train --setup[/yellow]")
            except Exception as e:
                console.print(f"  [yellow]Download failed: {e}[/yellow]")
                console.print(f"  [dim]Run later: trio train --setup[/dim]")

        config["providers"]["trio"] = {"default_model": model_name}
        config["agents"]["defaults"]["provider"] = "trio"
        config["agents"]["defaults"]["model"] = model_name
        console.print(f"\n  [green][OK] Model: {model_name} (runs locally, no internet needed)[/green]")

    elif choice == "3":
        api_key = Prompt.ask("  OpenAI API key")
        model = Prompt.ask("  Model", default="gpt-4o")
        config["providers"]["openai"] = {"apiKey": api_key, "default_model": model}
        config["agents"]["defaults"]["provider"] = "openai"
        config["agents"]["defaults"]["model"] = model
        console.print(f"\n  [green][OK] Provider: openai ({model})[/green]")

    elif choice == "4":
        api_key = Prompt.ask("  Anthropic API key")
        model = Prompt.ask("  Model", default="claude-sonnet-4-20250514")
        config["providers"]["anthropic"] = {"apiKey": api_key, "default_model": model}
        config["agents"]["defaults"]["provider"] = "anthropic"
        config["agents"]["defaults"]["model"] = model
        console.print(f"\n  [green][OK] Provider: anthropic ({model})[/green]")

    elif choice == "5":
        api_key = Prompt.ask("  Gemini API key")
        model = Prompt.ask("  Model", default="gemini-2.0-flash")
        config["providers"]["gemini"] = {"apiKey": api_key, "default_model": model}
        config["agents"]["defaults"]["provider"] = "gemini"
        config["agents"]["defaults"]["model"] = model
        console.print(f"\n  [green][OK] Provider: gemini ({model})[/green]")

    elif choice == "6":
        _setup_provider_manual(config)

    elif choice == "7" and ollama_info:
        best = _pick_best_model(ollama_info["models"])
        if len(ollama_info["models"]) > 1:
            model = Prompt.ask("  Ollama model", default=best)
        else:
            model = best
        config["providers"]["ollama"] = {
            "base_url": ollama_info.get("url", "http://localhost:11434"),
            "default_model": model,
        }
        config["agents"]["defaults"]["provider"] = "ollama"
        config["agents"]["defaults"]["model"] = model
        console.print(f"\n  [green][OK] Provider: ollama ({model})[/green]")

    console.print()


def _step_skills(config: dict) -> None:
    """Step 3/6: Skill Category Browser."""
    console.print(Panel(
        "[bold white]Step 3/6[/bold white]  [bold cyan]Skills[/bold cyan]",
        border_style="cyan", box=box.HEAVY,
    ))

    console.print("  [dim]Scanning skill library...[/dim]", end="")
    cat_counts = _scan_skill_categories()
    total = _get_total_skill_count()
    console.print(f"\r  [green]\u2713[/green] Found [bold]{total:,}[/bold] skills across {len(SKILL_CATEGORIES)} categories.\n")

    # Build the numbered menu
    cat_keys = list(SKILL_CATEGORIES.keys())
    for idx, key in enumerate(cat_keys, 1):
        meta = SKILL_CATEGORIES[key]
        count = cat_counts.get(key, 0)
        other = cat_counts.get("other", 0)
        console.print(f"    [cyan][{idx:>2}][/cyan]  {meta['icon']}  {meta['label']:<30s}  [dim]({count:,} skills)[/dim]")

    # Show uncategorized count
    other_count = cat_counts.get("other", 0)
    if other_count > 0:
        console.print(f"    [dim]       + {other_count:,} general-purpose skills (always included)[/dim]")

    console.print()
    console.print("  Enter category numbers (comma-separated), [cyan]all[/cyan] for everything,")
    console.print("  or press [cyan]Enter[/cyan] to select all.\n")

    selection = Prompt.ask("  Categories", default="all").strip()

    selected_keys: list[str] = []
    if selection.lower() in ("all", ""):
        selected_keys = list(cat_keys)
    else:
        for part in selection.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part)
                if 1 <= idx <= len(cat_keys):
                    selected_keys.append(cat_keys[idx - 1])
                else:
                    console.print(f"  [yellow]Skipping invalid number: {part}[/yellow]")
            else:
                # Allow category names too
                if part in cat_keys:
                    selected_keys.append(part)

    if not selected_keys:
        selected_keys = list(cat_keys)
        console.print("  [dim]No valid selection, enabling all categories.[/dim]")

    # Remove duplicates while preserving order
    seen = set()
    unique_keys = []
    for k in selected_keys:
        if k not in seen:
            seen.add(k)
            unique_keys.append(k)
    selected_keys = unique_keys

    # Count total skills in selected categories
    enabled_count = sum(cat_counts.get(k, 0) for k in selected_keys) + other_count

    # Save to config
    if "skills" not in config:
        config["skills"] = {}
    config["skills"]["categories"] = selected_keys

    # Display summary
    labels = [SKILL_CATEGORIES[k]["icon"] + " " + SKILL_CATEGORIES[k]["label"] for k in selected_keys]
    console.print()
    for lbl in labels:
        console.print(f"  [green]\u2713[/green] {lbl}")
    console.print(f"\n  [bold green]\u2713 {enabled_count:,} skills enabled[/bold green]")
    console.print()


def _step_tools(config: dict) -> None:
    """Step 4/6: Tool Selection."""
    console.print(Panel(
        "[bold white]Step 4/6[/bold white]  [bold cyan]Tools[/bold cyan]",
        border_style="cyan", box=box.HEAVY,
    ))

    console.print("  Select which tools trio can use.\n")

    # Display tools with default states
    for idx, (tool_id, name, desc, default_on) in enumerate(AVAILABLE_TOOLS, 1):
        mark = "[green][x][/green]" if default_on else "[dim][ ][/dim]"
        console.print(f"    {mark}  [cyan]{idx:>2}[/cyan]. {name:<18s} [dim]{desc}[/dim]")

    console.print()
    console.print("  Options:")
    console.print("    [cyan]Enter[/cyan]       Accept defaults (recommended)")
    console.print("    [cyan]all[/cyan]         Enable every tool")
    console.print("    [cyan]1,5,7[/cyan]       Toggle specific tools by number")
    console.print()

    choice = Prompt.ask("  Selection", default="").strip()

    # Start with defaults
    enabled: dict[str, bool] = {}
    for tool_id, _name, _desc, default_on in AVAILABLE_TOOLS:
        enabled[tool_id] = default_on

    if choice.lower() == "all":
        for tool_id in enabled:
            enabled[tool_id] = True
    elif choice:
        # Toggle the specified numbers
        for part in choice.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part)
                if 1 <= idx <= len(AVAILABLE_TOOLS):
                    tool_id = AVAILABLE_TOOLS[idx - 1][0]
                    enabled[tool_id] = not enabled[tool_id]

    # Save to config
    config["tools"]["builtin"] = [tid for tid, on in enabled.items() if on]

    # Display result
    console.print()
    for tool_id, name, desc, _default in AVAILABLE_TOOLS:
        if enabled[tool_id]:
            console.print(f"  [green]\u2713[/green] {name}")
        else:
            console.print(f"  [dim]-  {name}[/dim]")

    enabled_count = sum(1 for v in enabled.values() if v)
    console.print(f"\n  [bold green]\u2713 {enabled_count} tools enabled[/bold green]")
    console.print()


def _step_channels(config: dict) -> None:
    """Step 5/6: Chat Channels."""
    console.print(Panel(
        "[bold white]Step 5/6[/bold white]  [bold cyan]Chat Channels[/bold cyan]",
        border_style="cyan", box=box.HEAVY,
    ))

    channels_info = [
        ("CLI",         "cli",          "Terminal / command line (always on)",     True,  []),
        ("Discord",     "discord",      "Discord bot integration",                False, ["token"]),
        ("Telegram",    "telegram",     "Telegram bot integration",               False, ["token"]),
        ("Slack",       "slack",        "Slack workspace bot",                    False, ["bot_token", "app_token"]),
        ("WhatsApp",    "whatsapp",     "WhatsApp Business API",                  False, ["phone_number_id", "access_token"]),
        ("Teams",       "teams",        "Microsoft Teams bot",                    False, ["app_id", "app_password"]),
        ("Google Chat", "google_chat",  "Google Workspace Chat",                  False, ["service_account_file"]),
        ("Signal",      "signal",       "Signal messenger",                       False, ["phone"]),
    ]

    if platform.system() == "Darwin":
        channels_info.append(("iMessage", "imessage", "Apple iMessage", False, []))

    console.print("  trio works in your terminal by default.")
    console.print("  You can also connect chat platforms:\n")

    for idx, (display, key, desc, default_on, _fields) in enumerate(channels_info, 1):
        if default_on:
            mark = "[green][x][/green]"
        else:
            mark = "[dim][ ][/dim]"
        console.print(f"    {mark}  [cyan]{idx:>2}[/cyan]. {display:<14s} [dim]{desc}[/dim]")

    console.print()
    console.print("  Options:")
    console.print("    [cyan]Enter[/cyan]       CLI only (default)")
    console.print("    [cyan]2,3,4[/cyan]       Enable channels by number")
    console.print("    [cyan]all[/cyan]         Enable all channels")
    console.print()

    choice = Prompt.ask("  Channels to enable", default="").strip()

    enabled_channels: list[str] = []

    if choice.lower() == "all":
        enabled_channels = [key for _, key, _, _, _ in channels_info if key != "cli"]
    elif choice:
        for part in choice.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part)
                if 1 <= idx <= len(channels_info):
                    ch = channels_info[idx - 1]
                    if ch[1] != "cli":
                        enabled_channels.append(ch[1])

    # Collect credentials for enabled channels
    if enabled_channels:
        console.print()
        for display, key, desc, _default_on, fields in channels_info:
            if key not in enabled_channels:
                continue

            config["channels"][key]["enabled"] = True
            console.print(f"  [bold]{display}[/bold] configuration:")

            for field in fields:
                value = Prompt.ask(f"    {field}")
                config["channels"][key][field] = value

            console.print(f"  [green]\u2713 {display} enabled[/green]\n")

    # Summary
    console.print()
    console.print(f"  [green]\u2713[/green] CLI (always on)")
    for display, key, _, _, _ in channels_info:
        if key in enabled_channels:
            console.print(f"  [green]\u2713[/green] {display}")

    if not enabled_channels:
        console.print("  [dim]Add channels later: trio channel add[/dim]")
    console.print()


def _step_workspace(config: dict) -> None:
    """Step 6/6: Workspace Setup."""
    console.print(Panel(
        "[bold white]Step 6/6[/bold white]  [bold cyan]Workspace Setup[/bold cyan]",
        border_style="cyan", box=box.HEAVY,
    ))

    # Create directories
    dirs = [
        ("Data",      get_trio_dir()),
        ("Workspace", get_workspace_dir()),
        ("Memory",    get_memory_dir()),
        ("Sessions",  get_sessions_dir()),
        ("Skills",    get_skills_dir()),
        ("Notes",     get_notes_dir()),
        ("Plugins",   get_plugins_dir()),
    ]

    for name, d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        console.print(f"  [green]\u2713[/green] {name:<12s} {_friendly_path(d)}")

    # Create SOUL.md
    soul_path = get_workspace_dir() / "SOUL.md"
    if not soul_path.exists():
        soul_path.write_text(
            "# trio Personality\n\n"
            "You are trio, a helpful and friendly AI assistant.\n"
            "Be concise, accurate, and helpful.\n"
            "Adapt your tone to match the user's style.\n",
            encoding="utf-8",
        )
        console.print(f"  [green]\u2713[/green] {'SOUL.md':<12s} {_friendly_path(soul_path)}")
    else:
        console.print(f"  [dim]-  SOUL.md already exists[/dim]")

    # Create USER.md
    user_path = get_workspace_dir() / "USER.md"
    if not user_path.exists():
        user_path.write_text(
            "# User Context\n\n"
            "Add information about yourself here.\n"
            "trio will use this to personalize responses.\n",
            encoding="utf-8",
        )
        console.print(f"  [green]\u2713[/green] {'USER.md':<12s} {_friendly_path(user_path)}")
    else:
        console.print(f"  [dim]-  USER.md already exists[/dim]")

    # Save config
    save_config(config)
    config_path = get_config_path()
    console.print(f"\n  [green]\u2713[/green] Config saved to {_friendly_path(config_path)}")
    console.print()


def _show_summary(config: dict) -> None:
    """Display the final summary panel after all steps complete."""
    provider = config["agents"]["defaults"]["provider"]
    model = config["agents"]["defaults"]["model"]
    config_path = get_config_path()

    # Skills summary
    skill_cats = config.get("skills", {}).get("categories", [])
    if skill_cats:
        skills_line = ", ".join(
            SKILL_CATEGORIES[k]["label"]
            for k in skill_cats
            if k in SKILL_CATEGORIES
        )
        if len(skill_cats) == len(SKILL_CATEGORIES):
            skills_line = f"All categories ({len(SKILL_CATEGORIES)})"
    else:
        skills_line = "All (default)"

    # Tools summary
    tools = config.get("tools", {}).get("builtin", [])
    tools_line = f"{len(tools)} tools enabled"

    # Channels summary
    active_channels = [
        name for name, ch_cfg in config.get("channels", {}).items()
        if ch_cfg.get("enabled")
    ]
    channels_line = ", ".join(active_channels) if active_channels else "CLI only"

    summary_text = (
        "[bold green]Setup complete![/bold green]\n"
        "\n"
        f"  [bold]Provider:[/bold]  {provider} / {model}\n"
        f"  [bold]Skills:[/bold]    {skills_line}\n"
        f"  [bold]Tools:[/bold]     {tools_line}\n"
        f"  [bold]Channels:[/bold]  {channels_line}\n"
        f"  [bold]Config:[/bold]    {_friendly_path(config_path)}\n"
        "\n"
        "  [bold]Next steps:[/bold]\n"
        "    [cyan]trio agent[/cyan]    Start chatting\n"
        "    [cyan]trio status[/cyan]   System overview\n"
        "    [cyan]trio doctor[/cyan]   Diagnose issues\n"
        "    [cyan]trio skills[/cyan]   Browse & manage skills"
    )

    console.print(Panel(
        summary_text,
        border_style="green",
        box=box.DOUBLE,
        title="[bold green] trio.ai [/bold green]",
        title_align="center",
        padding=(1, 2),
    ))
    console.print()


# ── Main entry point ─────────────────────────────────────────────────────────

async def run_onboard():
    """Interactive 6-step setup wizard for trio.ai."""

    # ── Welcome banner ────────────────────────────────────────────────
    console.print()
    console.print(Panel(
        "[bold cyan]Welcome to trio.ai[/bold cyan]\n"
        "[dim]Your AI, everywhere.[/dim]\n\n"
        "This wizard will configure your environment in 6 quick steps.",
        border_style="cyan",
        box=box.DOUBLE,
        title="[bold cyan] Onboarding [/bold cyan]",
        title_align="center",
        padding=(1, 2),
    ))

    config_path = get_config_path()

    # Check if already configured
    if config_path.exists():
        if not Confirm.ask("\n[yellow]Existing config found. Re-run setup?[/yellow]", default=False):
            console.print("[green]Keeping existing configuration.[/green]\n")
            return

    config = DEFAULT_CONFIG.copy()

    # ── Step 1: System Check ──────────────────────────────────────────
    ollama_info = _step_system_check()

    # ── Step 2: AI Provider ───────────────────────────────────────────
    _step_provider(config, ollama_info)

    # ── Step 3: Skills ────────────────────────────────────────────────
    _step_skills(config)

    # ── Step 4: Tools ─────────────────────────────────────────────────
    _step_tools(config)

    # ── Step 5: Chat Channels ─────────────────────────────────────────
    _step_channels(config)

    # ── Step 6: Workspace Setup ───────────────────────────────────────
    _step_workspace(config)

    # ── Summary ───────────────────────────────────────────────────────
    _show_summary(config)
