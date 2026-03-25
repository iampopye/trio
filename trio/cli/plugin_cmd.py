"""CLI handler for trio plugin subcommand."""

from rich.console import Console
from rich.table import Table

console = Console()


async def run_plugin(args):
    from trio.plugins.manager import PluginManager

    manager = PluginManager()
    action = getattr(args, "plugin_action", None)

    if action == "list":
        plugins = manager.list_plugins()
        if not plugins:
            console.print("[yellow]No plugins installed.[/yellow]")
            console.print("[dim]Install plugins: trio plugin install <path>[/dim]")
            return

        table = Table(title="Installed Plugins")
        table.add_column("Name", style="cyan")
        table.add_column("Version")
        table.add_column("Status")
        table.add_column("Tools")
        table.add_column("Skills")
        table.add_column("Description")

        for p in plugins:
            status = "[green]enabled[/green]" if p.enabled else "[red]disabled[/red]"
            table.add_row(
                p.name, p.version, status,
                str(len(p.tools)), str(len(p.skills)),
                p.description[:50],
            )
        console.print(table)

    elif action == "install":
        path = args.path
        try:
            name = manager.install(path)
            console.print(f"[green]Plugin '{name}' installed successfully.[/green]")
        except Exception as e:
            console.print(f"[red]Install failed: {e}[/red]")

    elif action == "uninstall":
        name = args.name
        if manager.uninstall(name):
            console.print(f"[green]Plugin '{name}' uninstalled.[/green]")
        else:
            console.print(f"[red]Plugin '{name}' not found.[/red]")

    elif action == "enable":
        if manager.enable(args.name):
            console.print(f"[green]Plugin '{args.name}' enabled.[/green]")
        else:
            console.print(f"[red]Plugin '{args.name}' not found.[/red]")

    elif action == "disable":
        if manager.disable(args.name):
            console.print(f"[green]Plugin '{args.name}' disabled.[/green]")
        else:
            console.print(f"[red]Plugin '{args.name}' not found.[/red]")

    else:
        console.print("[bold]trio plugin[/bold] — manage plugins\n")
        console.print("  [cyan]trio plugin list[/cyan]               — List installed plugins")
        console.print("  [cyan]trio plugin install <path>[/cyan]     — Install from local path")
        console.print("  [cyan]trio plugin uninstall <name>[/cyan]   — Remove a plugin")
        console.print("  [cyan]trio plugin enable <name>[/cyan]      — Enable a plugin")
        console.print("  [cyan]trio plugin disable <name>[/cyan]     — Disable a plugin")
