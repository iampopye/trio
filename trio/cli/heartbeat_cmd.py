"""CLI handler for trio heartbeat subcommand."""

import asyncio
from rich.console import Console

from trio.core.config import load_config, get_workspace_dir, get_memory_dir

console = Console()


async def run_heartbeat(action: str | None):
    config = load_config()
    hb_config = config.get("heartbeat", {})

    if action == "status":
        enabled = hb_config.get("enabled", False)
        interval = hb_config.get("interval_seconds", 300)
        hb_file = get_workspace_dir() / "HEARTBEAT.md"
        notify = hb_config.get("notify_channel", "") or "(none)"

        console.print(f"[bold]Heartbeat Status[/bold]")
        console.print(f"  Enabled:    {'[green]Yes[/green]' if enabled else '[red]No[/red]'}")
        console.print(f"  Interval:   {interval}s ({interval // 60}m)")
        console.print(f"  File:       {hb_file}")
        console.print(f"  File exists: {'Yes' if hb_file.exists() else 'No'}")
        console.print(f"  Notify:     {notify}")

    elif action == "log":
        log_path = get_memory_dir() / "heartbeat.log"
        if not log_path.exists():
            console.print("[yellow]No heartbeat log yet.[/yellow]")
            return
        content = log_path.read_text(encoding="utf-8")
        # Show last 2000 chars
        if len(content) > 2000:
            content = "... (truncated)\n" + content[-2000:]
        console.print(content)

    elif action == "edit":
        import subprocess
        import os
        hb_file = get_workspace_dir() / "HEARTBEAT.md"
        if not hb_file.exists():
            hb_file.write_text(
                "# Heartbeat Checklist\n\n"
                "- [ ] Example task\n",
                encoding="utf-8",
            )
        editor = os.environ.get("EDITOR", "notepad" if os.name == "nt" else "nano")
        subprocess.run([editor, str(hb_file)])

    else:
        console.print("[bold]trio heartbeat[/bold] — manage the heartbeat daemon\n")
        console.print("  [cyan]trio heartbeat status[/cyan]  — Show heartbeat config and status")
        console.print("  [cyan]trio heartbeat log[/cyan]     — Show recent heartbeat log")
        console.print("  [cyan]trio heartbeat edit[/cyan]    — Edit HEARTBEAT.md checklist")
        console.print("\nEnable in config: [dim]heartbeat.enabled = true[/dim]")
