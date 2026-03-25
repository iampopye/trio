"""trioai status — show system status."""

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

    console.print(Panel.fit("[bold cyan]trioai status[/bold cyan]", border_style="cyan"))

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
        presets = ["trio-nano.pt", "trio-small.pt", "trio-medium.pt"]
        found = [p.stem for p in model_dir.glob("*.pt")] if model_dir.exists() else []
        if found:
            console.print(f"Trio model: [green]ready[/green] ({', '.join(found)})")
        else:
            console.print("Trio model: [yellow]will auto-initialize on first use[/yellow]")
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
    tools = config.get("tools", {}).get("builtin", [])
    mcp = config.get("tools", {}).get("mcpServers", {})
    console.print(f"\nTools: {len(tools)} built-in, {len(mcp)} MCP servers")

    console.print()
