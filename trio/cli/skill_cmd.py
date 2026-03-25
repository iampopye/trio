"""CLI handler for trio skill subcommand."""

from rich.console import Console
from rich.table import Table

from trio.core.config import get_skills_dir

console = Console()


async def run_skill(args):
    action = getattr(args, "skill_action", None)

    if action == "list":
        skills_dir = get_skills_dir()
        skills = sorted(skills_dir.glob("*.md"))
        if not skills:
            console.print("[yellow]No skills installed.[/yellow]")
            console.print("[dim]Install skills: trio skill install <name>[/dim]")
            return

        table = Table(title=f"Installed Skills ({len(skills)})")
        table.add_column("Name", style="cyan")
        table.add_column("Size")

        for s in skills:
            size = s.stat().st_size
            table.add_row(s.stem, f"{size}B")
        console.print(table)

    elif action == "search":
        query = args.query
        console.print(f"[dim]Searching TrioHub for '{query}'...[/dim]")

        from trio.hub.registry import TrioHubRegistry
        registry = TrioHubRegistry()
        results = await registry.search(query)

        if not results:
            console.print(f"[yellow]No results for '{query}'[/yellow]")
            return

        table = Table(title=f"TrioHub Results: '{query}'")
        table.add_column("Name", style="cyan")
        table.add_column("Type")
        table.add_column("Description")
        table.add_column("Author")

        for r in results[:20]:
            table.add_row(
                r.get("name", "?"),
                r.get("type", "?"),
                r.get("description", "")[:60],
                r.get("author", ""),
            )
        console.print(table)

    elif action == "install":
        name = args.name
        console.print(f"[dim]Installing skill '{name}' from TrioHub...[/dim]")

        from trio.hub.installer import HubInstaller
        installer = HubInstaller()
        if await installer.install_skill(name):
            console.print(f"[green]Skill '{name}' installed![/green]")
        else:
            console.print(f"[red]Failed to install skill '{name}'[/red]")

    else:
        console.print("[bold]trio skill[/bold] — manage skills\n")
        console.print("  [cyan]trio skill list[/cyan]             — List installed skills")
        console.print("  [cyan]trio skill search <query>[/cyan]   — Search TrioHub")
        console.print("  [cyan]trio skill install <name>[/cyan]   — Install from TrioHub")
