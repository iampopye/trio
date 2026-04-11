"""trio repo — manage multiple project workspaces."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from rich.console import Console
from rich.table import Table
from rich import box

from trio.core.repo_registry import RepoRegistry

console = Console()


async def run_repo(args) -> None:
    """Dispatch trio repo sub-commands."""
    action = getattr(args, "repo_action", None)
    registry = RepoRegistry()

    if action is None or action == "list":
        _show_list(registry)
    elif action == "register":
        _register(registry, args.alias, args.path, getattr(args, "description", ""))
    elif action == "unregister":
        _unregister(registry, args.alias)
    elif action == "use":
        _use(registry, args.alias)
    elif action == "search":
        _search(registry, args.query)
    else:
        console.print(f"[red]Unknown action: {action}[/red]")


def _show_list(registry: RepoRegistry) -> None:
    repos = registry.list()
    if not repos:
        console.print("\n[yellow]No repos registered yet.[/yellow]")
        console.print("Add one with: [cyan]trio repo register <alias> <path>[/cyan]\n")
        return

    active = registry.get_active()
    active_alias = active.alias if active else None

    table = Table(title="Registered repos", box=box.MINIMAL_HEAVY_HEAD)
    table.add_column("", style="green", width=2)
    table.add_column("Alias", style="cyan")
    table.add_column("Path", style="white")
    table.add_column("Lang", style="yellow")
    table.add_column("Git", style="dim")
    table.add_column("Status", style="white")

    for repo in repos:
        marker = "▶" if repo.alias == active_alias else " "
        status = "[green]ok[/green]" if repo.exists() else "[red]missing[/red]"
        git = "✓" if repo.is_git else "—"
        table.add_row(marker, repo.alias, repo.path, repo.language or "—", git, status)

    console.print()
    console.print(table)
    console.print()
    if active:
        console.print(f"  Active: [cyan]{active.alias}[/cyan]\n")


def _register(registry: RepoRegistry, alias: str, path: str, description: str) -> None:
    try:
        entry = registry.register(alias, path, description=description)
        console.print(f"\n[green]✓[/green] Registered [cyan]{entry.alias}[/cyan] → {entry.path}")
        console.print(f"  Language: {entry.language or 'unknown'}")
        if entry.is_git:
            console.print("  Git repository: [green]yes[/green]\n")
        else:
            console.print("  Git repository: [dim]no[/dim]\n")
    except ValueError as e:
        console.print(f"\n[red]✗[/red] {e}\n")


def _unregister(registry: RepoRegistry, alias: str) -> None:
    if registry.unregister(alias):
        console.print(f"\n[green]✓[/green] Unregistered [cyan]{alias}[/cyan]\n")
    else:
        console.print(f"\n[red]✗[/red] No repo with alias [cyan]{alias}[/cyan]\n")


def _use(registry: RepoRegistry, alias: str) -> None:
    if registry.set_active(alias):
        console.print(f"\n[green]✓[/green] Active repo: [cyan]{alias}[/cyan]\n")
    else:
        console.print(f"\n[red]✗[/red] No repo with alias [cyan]{alias}[/cyan]\n")
        console.print("Run [cyan]trio repo list[/cyan] to see available repos.\n")


def _search(registry: RepoRegistry, query: str) -> None:
    results = registry.search(query)
    if not results:
        console.print(f"\nNo files matching [cyan]{query}[/cyan] in any registered repo.\n")
        return

    console.print(f"\nFound [cyan]{len(results)}[/cyan] match(es) for [cyan]{query}[/cyan]:\n")
    last_repo = None
    for repo, path in results:
        if repo.alias != last_repo:
            console.print(f"[yellow]{repo.alias}[/yellow]  [dim]({repo.path})[/dim]")
            last_repo = repo.alias
        rel = path.relative_to(repo.path) if str(path).startswith(repo.path) else path
        console.print(f"  • {rel}")
    console.print()
