"""trio status — show system status."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from trio.core.config import load_config, get_config_path, get_trio_dir


def _friendly_path(p: Path) -> str:
    """Show ~/.trio/... instead of full absolute path for privacy."""
    try:
        rel = p.relative_to(Path.home())
        return f"~/{rel.as_posix()}"
    except ValueError:
        return p.name
from trio.core.session import SessionManager
from trio.core.rag import RAGStore

console = Console()


async def run_status():
    """Show trio system status."""
    config = load_config()

    console.print(Panel.fit("[bold cyan]trio status[/bold cyan]", border_style="cyan"))

    # Config
    console.print(f"\nConfig: {_friendly_path(get_config_path())}")
    console.print(f"Data dir: {_friendly_path(get_trio_dir())}")

    # Provider
    defaults = config.get("agents", {}).get("defaults", {})
    provider = defaults.get("provider", "trio")
    model = defaults.get("model", "?")
    console.print(f"\nProvider: [cyan]{provider}[/cyan]")
    console.print(f"Default model: [cyan]{model}[/cyan]")

    # Check provider status
    if provider == "trio":
        from pathlib import Path as _P
        model_dir = _P.home() / ".trio" / "models"
        found = list(model_dir.glob("*.pt")) if model_dir.exists() else []
        if found:
            console.print(f"trio-max: [green]ready[/green]")
        else:
            console.print("trio-max: [yellow]will deploy on first use[/yellow]")
    elif provider == "ollama":
        base_url = config.get("providers", {}).get("ollama", {}).get("base_url", "http://localhost:11434")
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{base_url}/api/tags", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        models = [m["name"] for m in data.get("models", [])]
                        console.print(f"Ollama: [green]connected[/green] ({len(models)} models)")
                    else:
                        console.print(f"Ollama: [red]error (status {resp.status})[/red]")
        except Exception:
            console.print(f"Ollama: [red]not reachable[/red] at {base_url}")

    # Channels
    channels = config.get("channels", {})
    channel_table = Table(title="Channels")
    channel_table.add_column("Channel", style="cyan")
    channel_table.add_column("Status")

    for name, ch_config in channels.items():
        enabled = ch_config.get("enabled", False)
        status = "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]"
        channel_table.add_row(name, status)
    console.print(channel_table)

    # Sessions
    sessions = SessionManager()
    session_list = sessions.list_sessions()
    console.print(f"\nSessions: {len(session_list)}")

    # RAG
    try:
        store = RAGStore()
        collections = store.list_collections()
        total_docs = sum(RAGStore(c).count() for c in collections) if collections else 0
        console.print(f"RAG collections: {len(collections)} ({total_docs} documents)")
    except Exception:
        console.print("RAG: not initialized")

    # Tools
    tools_cfg = config.get("tools", {}).get("builtin", [])
    mcp = config.get("tools", {}).get("mcpServers", {})
    # Also count tools that register_builtins can load
    try:
        from trio.tools.base import register_builtins
        available = register_builtins(config)
        console.print(f"\nTools: {len(available)} built-in, {len(mcp)} MCP servers")
        console.print(f"  Built-in: {', '.join(t.name for t in available)}")
    except Exception:
        console.print(f"\nTools: {len(tools_cfg)} built-in, {len(mcp)} MCP servers")
        console.print(f"  Built-in: {', '.join(tools_cfg)}")

    # Plugins
    try:
        from trio.plugins.manager import PluginManager
        pm = PluginManager()
        plugins = pm.list_plugins()
        enabled = sum(1 for p in plugins if p.enabled)
        console.print(f"\nPlugins: {len(plugins)} installed, {enabled} enabled")
        for p in plugins:
            status = "[green]on[/green]" if p.enabled else "[red]off[/red]"
            console.print(f"  {p.name} v{p.version} [{status}]")
    except Exception:
        console.print("\nPlugins: none")

    # Heartbeat
    hb = config.get("heartbeat", {})
    if hb.get("enabled"):
        console.print(f"\nHeartbeat: [green]enabled[/green] (every {hb.get('interval_seconds', 300)}s)")
    else:
        console.print("\nHeartbeat: [dim]disabled[/dim]")

    # Skills
    from trio.core.config import get_skills_dir
    skills_dir = get_skills_dir()
    skill_count = len(list(skills_dir.glob("*.md")))
    console.print(f"Skills: {skill_count}")

    console.print()
