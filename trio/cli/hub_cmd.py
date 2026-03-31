"""CLI handler for trio hub subcommand."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from rich.console import Console
from rich.table import Table

console = Console()


async def run_hub(args):
    action = getattr(args, "hub_action", None)

    if action == "search":
        query = args.query
        console.print(f"[dim]Searching TrioHub for '{query}'...[/dim]")

        from trio.hub.registry import TrioHubRegistry
        registry = TrioHubRegistry()
        results = await registry.search(query)

        if not results:
            console.print(f"[yellow]No results for '{query}'[/yellow]")
            return

        table = Table(title=f"TrioHub: '{query}'")
        table.add_column("Name", style="cyan")
        table.add_column("Type")
        table.add_column("Downloads", justify="right")
        table.add_column("Description")

        for r in results[:20]:
            table.add_row(
                r.get("name", "?"),
                r.get("type", "?"),
                str(r.get("downloads", 0)),
                r.get("description", "")[:60],
            )
        console.print(table)

    elif action == "trending":
        console.print("[dim]Fetching trending from TrioHub...[/dim]")

        from trio.hub.registry import TrioHubRegistry
        registry = TrioHubRegistry()
        trending = await registry.get_trending()

        if not trending:
            console.print("[yellow]TrioHub index not available yet.[/yellow]")
            return

        table = Table(title="Trending on TrioHub")
        table.add_column("#", style="dim")
        table.add_column("Name", style="cyan")
        table.add_column("Type")
        table.add_column("Downloads", justify="right")
        table.add_column("Description")

        for i, r in enumerate(trending, 1):
            table.add_row(
                str(i),
                r.get("name", "?"),
                r.get("type", "?"),
                str(r.get("downloads", 0)),
                r.get("description", "")[:50],
            )
        console.print(table)

    else:
        console.print("[bold]trio hub[/bold] — TrioHub community registry\n")
        console.print("  [cyan]trio hub search <query>[/cyan]  — Search skills and plugins")
        console.print("  [cyan]trio hub trending[/cyan]        — Show trending items")
