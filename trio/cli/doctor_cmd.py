"""trio doctor — diagnose and repair system issues."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import json
import logging
import os
import platform
import shutil
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from trio.core.config import (
    load_config, get_trio_dir, get_config_path, get_workspace_dir,
    get_memory_dir, get_sessions_dir, get_skills_dir, get_notes_dir,
    get_plugins_dir,
)

console = Console()
logger = logging.getLogger(__name__)


class DoctorCheck:
    """Result of a single diagnostic check."""

    def __init__(self, name: str, passed: bool, message: str, fixable: bool = False, fix_fn=None):
        self.name = name
        self.passed = passed
        self.message = message
        self.fixable = fixable
        self.fix_fn = fix_fn


async def run_doctor(fix: bool = False):
    """Run all diagnostic checks."""
    console.print(Panel.fit("[bold cyan]trio doctor[/bold cyan]", border_style="cyan"))
    console.print()

    checks: list[DoctorCheck] = []

    # 1. Python version
    checks.append(_check_python_version())

    # 2. Config file
    checks.append(_check_config())

    # 2b. Config completeness (missing tools/channels)
    checks.extend(_check_config_completeness())

    # 3. Directories
    checks.extend(_check_directories())

    # 4. Workspace files
    checks.extend(_check_workspace_files())

    # 5. Provider
    checks.append(await _check_provider())

    # 6. Dependencies
    checks.extend(_check_dependencies())

    # 7. Model checkpoint
    checks.append(_check_model())

    # 8. Skills
    checks.append(_check_skills())

    # 9. Plugins
    checks.append(_check_plugins())

    # 10. Channel configs
    checks.extend(_check_channels())

    # 11. Security
    checks.extend(_check_security())

    # 12. Heartbeat
    checks.append(_check_heartbeat())

    # Display results
    console.print()
    passed = 0
    failed = 0
    fixed = 0

    for check in checks:
        if check.passed:
            console.print(f"  [green]OK[/green]  {check.name}: {check.message}")
            passed += 1
        else:
            if fix and check.fixable and check.fix_fn:
                try:
                    check.fix_fn()
                    console.print(f"  [yellow]FIX[/yellow] {check.name}: {check.message} -> fixed")
                    fixed += 1
                except Exception as e:
                    console.print(f"  [red]FAIL[/red] {check.name}: {check.message} (fix failed: {e})")
                    failed += 1
            else:
                icon = "[yellow]WARN[/yellow]" if check.fixable else "[red]FAIL[/red]"
                console.print(f"  {icon} {check.name}: {check.message}")
                failed += 1

    console.print()
    console.print(f"  Results: [green]{passed} passed[/green]", end="")
    if fixed:
        console.print(f", [yellow]{fixed} fixed[/yellow]", end="")
    if failed:
        console.print(f", [red]{failed} issues[/red]", end="")
    console.print()

    if failed > 0 and not fix:
        console.print("\n  [dim]Run [cyan]trio doctor --fix[/cyan] to auto-repair fixable issues[/dim]")

    console.print()


def _check_python_version() -> DoctorCheck:
    v = sys.version_info
    if v >= (3, 10):
        return DoctorCheck("Python", True, f"{v.major}.{v.minor}.{v.micro}")
    return DoctorCheck("Python", False, f"{v.major}.{v.minor} (need 3.10+)")


def _check_config() -> DoctorCheck:
    config_path = get_config_path()
    if config_path.exists():
        try:
            config = load_config()
            return DoctorCheck("Config", True, str(config_path))
        except Exception as e:
            return DoctorCheck("Config", False, f"Invalid JSON: {e}", fixable=True,
                               fix_fn=lambda: _fix_config())
    return DoctorCheck("Config", False, "Missing — run 'trio onboard'", fixable=True,
                       fix_fn=lambda: _fix_config())


def _fix_config():
    from trio.core.config import DEFAULT_CONFIG, save_config
    save_config(DEFAULT_CONFIG)


def _check_config_completeness() -> list[DoctorCheck]:
    """Check that config has all expected tools and channels from DEFAULT_CONFIG."""
    from trio.core.config import DEFAULT_CONFIG, save_config
    checks = []
    config = load_config()

    # Check tools
    expected_tools = set(DEFAULT_CONFIG.get("tools", {}).get("builtin", []))
    current_tools = set(config.get("tools", {}).get("builtin", []))
    missing_tools = expected_tools - current_tools
    if missing_tools:
        def _fix_tools():
            c = load_config()
            c.setdefault("tools", {}).setdefault("builtin", [])
            for t in missing_tools:
                if t not in c["tools"]["builtin"]:
                    c["tools"]["builtin"].append(t)
            save_config(c)
        checks.append(DoctorCheck(
            "Config: tools", False,
            f"Missing tools: {', '.join(sorted(missing_tools))}",
            fixable=True, fix_fn=_fix_tools,
        ))

    # Check channels
    expected_channels = set(DEFAULT_CONFIG.get("channels", {}).keys())
    current_channels = set(config.get("channels", {}).keys())
    missing_channels = expected_channels - current_channels
    if missing_channels:
        def _fix_channels():
            c = load_config()
            c.setdefault("channels", {})
            for ch in missing_channels:
                if ch not in c["channels"]:
                    c["channels"][ch] = DEFAULT_CONFIG["channels"][ch]
            save_config(c)
        checks.append(DoctorCheck(
            "Config: channels", False,
            f"Missing channel configs: {', '.join(sorted(missing_channels))}",
            fixable=True, fix_fn=_fix_channels,
        ))

    # Check heartbeat config
    if "heartbeat" not in config:
        def _fix_heartbeat():
            c = load_config()
            c["heartbeat"] = DEFAULT_CONFIG.get("heartbeat", {})
            save_config(c)
        checks.append(DoctorCheck(
            "Config: heartbeat", False,
            "Missing heartbeat config section",
            fixable=True, fix_fn=_fix_heartbeat,
        ))

    return checks


def _check_directories() -> list[DoctorCheck]:
    checks = []
    dirs = {
        "Data dir": get_trio_dir(),
        "Workspace": get_workspace_dir(),
        "Memory": get_memory_dir(),
        "Sessions": get_sessions_dir(),
        "Skills": get_skills_dir(),
        "Notes": get_notes_dir(),
        "Plugins": get_plugins_dir(),
    }
    for name, path in dirs.items():
        if path.exists():
            checks.append(DoctorCheck(name, True, str(path)))
        else:
            checks.append(DoctorCheck(name, False, f"Missing: {path}", fixable=True,
                                      fix_fn=lambda p=path: p.mkdir(parents=True, exist_ok=True)))
    return checks


def _check_workspace_files() -> list[DoctorCheck]:
    checks = []
    ws = get_workspace_dir()

    soul = ws / "SOUL.md"
    if soul.exists():
        checks.append(DoctorCheck("SOUL.md", True, "Personality configured"))
    else:
        checks.append(DoctorCheck("SOUL.md", False, "Missing personality file", fixable=True,
                                  fix_fn=lambda: soul.write_text(
                                      "# trio Personality\n\nYou are trio, a helpful AI assistant.\n",
                                      encoding="utf-8")))

    user = ws / "USER.md"
    if user.exists():
        checks.append(DoctorCheck("USER.md", True, "User context configured"))
    else:
        checks.append(DoctorCheck("USER.md", False, "Missing user context", fixable=True,
                                  fix_fn=lambda: user.write_text(
                                      "# User Context\n\nAdd info about yourself here.\n",
                                      encoding="utf-8")))

    return checks


async def _check_provider() -> DoctorCheck:
    config = load_config()
    provider = config.get("agents", {}).get("defaults", {}).get("provider", "trio")

    if provider == "trio":
        model_dir = Path.home() / ".trio" / "models"
        found = list(model_dir.glob("*.pt")) if model_dir.exists() else []
        if found:
            return DoctorCheck("Provider", True, f"trio (local model: {found[0].name})")
        return DoctorCheck("Provider", True, "trio (will auto-download on first use)")

    elif provider == "ollama":
        base_url = config.get("providers", {}).get("ollama", {}).get("base_url", "http://localhost:11434")
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{base_url}/api/tags",
                                       timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        count = len(data.get("models", []))
                        return DoctorCheck("Provider", True, f"ollama ({count} models at {base_url})")
        except Exception:
            pass  # nosec B110 — intentional silent fallback
        return DoctorCheck("Provider", False, f"ollama not reachable at {base_url}")

    else:
        api_key = config.get("providers", {}).get(provider, {}).get("apiKey", "")
        if api_key:
            masked = api_key[:8] + "..." + api_key[-4:] if len(api_key) > 12 else "***"
            return DoctorCheck("Provider", True, f"{provider} (key: {masked})")
        return DoctorCheck("Provider", False, f"{provider} — no API key configured")


def _check_dependencies() -> list[DoctorCheck]:
    checks = []
    optional_deps = {
        "discord.py": "discord",
        "telebot": "telegram",
        "aiohttp": "core/channels",
        "tiktoken": "model training",
        "torch": "model inference",
        "playwright": "browser tool",
        "rich": "CLI interface",
    }
    for module, purpose in optional_deps.items():
        try:
            __import__(module)
            checks.append(DoctorCheck(f"Dep: {module}", True, f"installed ({purpose})"))
        except ImportError:
            checks.append(DoctorCheck(f"Dep: {module}", False, f"not installed ({purpose})",
                                      fixable=False))
    return checks


def _check_model() -> DoctorCheck:
    model_dir = Path.home() / ".trio" / "models"
    if not model_dir.exists():
        return DoctorCheck("Model", False, "No models directory", fixable=True,
                           fix_fn=lambda: model_dir.mkdir(parents=True, exist_ok=True))
    checkpoints = list(model_dir.glob("*.pt"))
    if checkpoints:
        sizes = [f"{f.name} ({f.stat().st_size / 1e6:.0f}MB)" for f in checkpoints]
        return DoctorCheck("Model", True, ", ".join(sizes))
    return DoctorCheck("Model", True, "No local model (will auto-download)")


def _check_skills() -> DoctorCheck:
    skills_dir = get_skills_dir()
    builtin_dir = Path(__file__).parent.parent / "skills" / "builtin"
    user_count = len(list(skills_dir.glob("*.md")))
    builtin_count = len(list(builtin_dir.glob("*.md"))) if builtin_dir.exists() else 0
    return DoctorCheck("Skills", True, f"{builtin_count} built-in, {user_count} user")


def _check_plugins() -> DoctorCheck:
    plugins_dir = get_plugins_dir()
    plugins = [d for d in plugins_dir.iterdir() if d.is_dir() and (d / "plugin.json").exists()] \
        if plugins_dir.exists() else []
    return DoctorCheck("Plugins", True, f"{len(plugins)} installed")


def _check_channels() -> list[DoctorCheck]:
    checks = []
    config = load_config()
    channels = config.get("channels", {})

    for name, ch_config in channels.items():
        enabled = ch_config.get("enabled", False)
        if not enabled:
            continue

        # Check for required config
        issues = []
        if name == "discord" and not ch_config.get("token"):
            issues.append("missing token")
        elif name == "telegram" and not ch_config.get("token"):
            issues.append("missing token")
        elif name == "slack" and not ch_config.get("bot_token"):
            issues.append("missing bot_token")
        elif name == "whatsapp" and not ch_config.get("access_token"):
            issues.append("missing access_token")
        elif name == "teams" and not ch_config.get("app_id"):
            issues.append("missing app_id")

        if issues:
            checks.append(DoctorCheck(f"Channel: {name}", False,
                                      f"enabled but {', '.join(issues)}"))
        else:
            checks.append(DoctorCheck(f"Channel: {name}", True, "configured"))

    return checks


def _check_security() -> list[DoctorCheck]:
    checks = []
    config = load_config()
    channels = config.get("channels", {})

    # Check for open DM policies
    for name, ch_config in channels.items():
        if not ch_config.get("enabled"):
            continue
        dm_policy = ch_config.get("dm_policy", "pairing")
        if dm_policy == "open":
            checks.append(DoctorCheck(
                f"Security: {name}", False,
                f"DM policy is 'open' — anyone can message your bot. "
                f"Consider 'pairing' mode for security."
            ))

    # Check guardrails
    guardrails = config.get("guardrails", {}).get("enabled", True)
    if not guardrails:
        checks.append(DoctorCheck("Security: guardrails", False,
                                  "Guardrails disabled — input/output filtering is off"))
    else:
        checks.append(DoctorCheck("Security: guardrails", True, "enabled"))

    return checks


def _check_heartbeat() -> DoctorCheck:
    config = load_config()
    hb = config.get("heartbeat", {})
    if hb.get("enabled"):
        hb_file = get_workspace_dir() / "HEARTBEAT.md"
        if hb_file.exists():
            return DoctorCheck("Heartbeat", True,
                               f"enabled (every {hb.get('interval_seconds', 300)}s)")
        return DoctorCheck("Heartbeat", False, "enabled but HEARTBEAT.md missing", fixable=True,
                           fix_fn=lambda: hb_file.write_text(
                               "# Heartbeat Checklist\n\n- [ ] Example task\n",
                               encoding="utf-8"))
    return DoctorCheck("Heartbeat", True, "disabled")
