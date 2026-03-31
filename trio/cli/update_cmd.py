"""trio update — self-update command."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import subprocess  # nosec B404
import sys

from rich.console import Console

console = Console()


async def run_update(channel: str = "stable"):
    """Update trio to the latest version."""
    console.print("[bold]trio update[/bold]\n")

    # Detect install method
    is_git = _is_git_install()

    if is_git:
        await _update_git(channel)
    else:
        await _update_pip(channel)


def _is_git_install() -> bool:
    """Check if trio is installed from git (dev) or pip (release)."""
    import trio
    pkg_dir = str(trio.__file__)
    # If we're in a git repo, it's a dev install
    from pathlib import Path
    check = Path(pkg_dir).parent.parent / ".git"
    return check.exists()


async def _update_git(channel: str):
    """Update from git source."""
    import trio
    from pathlib import Path

    repo_dir = Path(trio.__file__).parent.parent
    console.print(f"[dim]Git install detected at: {repo_dir}[/dim]")

    # Check for uncommitted changes
    result = subprocess.run(  # nosec B603 B607
        ["git", "status", "--porcelain"],
        cwd=str(repo_dir), capture_output=True, text=True,
    )
    if result.stdout.strip():
        console.print("[yellow]Warning: You have uncommitted changes.[/yellow]")
        console.print("[dim]Stash or commit them first, then retry.[/dim]")
        return

    # Fetch latest
    console.print("[dim]Fetching latest...[/dim]")
    subprocess.run(["git", "fetch", "--all", "--prune"], cwd=str(repo_dir))  # nosec B603 B607

    # Get current and remote SHA
    local = subprocess.run(  # nosec B603 B607
        ["git", "rev-parse", "HEAD"],
        cwd=str(repo_dir), capture_output=True, text=True,
    ).stdout.strip()

    remote = subprocess.run(  # nosec B603 B607
        ["git", "rev-parse", "origin/main"],
        cwd=str(repo_dir), capture_output=True, text=True,
    ).stdout.strip()

    if local == remote:
        console.print("[green]Already up to date![/green]")
        return

    # Pull
    console.print(f"[dim]Updating {local[:8]} → {remote[:8]}...[/dim]")
    result = subprocess.run(  # nosec B603 B607
        ["git", "pull", "--rebase", "origin", "main"],
        cwd=str(repo_dir),
    )
    if result.returncode != 0:
        console.print("[red]Git pull failed. Resolve conflicts and retry.[/red]")
        return

    # Reinstall
    console.print("[dim]Reinstalling...[/dim]")
    subprocess.run([sys.executable, "-m", "pip", "install", "-e", "."],  # nosec B603 B607
                   cwd=str(repo_dir))

    console.print("[green]Update complete![/green]")

    # Run doctor
    console.print("\n[dim]Running doctor...[/dim]")
    from trio.cli.doctor_cmd import run_doctor
    await run_doctor(fix=True)


async def _update_pip(channel: str):
    """Update from PyPI."""
    console.print("[dim]PyPI install detected[/dim]")

    # Get current version
    try:
        from importlib.metadata import version
        current = version("trio-ai")
    except Exception:
        current = "unknown"

    console.print(f"[dim]Current version: {current}[/dim]")
    console.print("[dim]Checking for updates...[/dim]")

    # Upgrade
    tag = "trio-ai" if channel == "stable" else f"trio-ai=={channel}"
    result = subprocess.run(  # nosec B603 B607
        [sys.executable, "-m", "pip", "install", "--upgrade", tag],
        capture_output=True, text=True,
    )

    if result.returncode == 0:
        # Get new version
        try:
            # Force reimport
            new_ver = subprocess.run(  # nosec B603 B607
                [sys.executable, "-c", "from importlib.metadata import version; print(version('trio-ai'))"],
                capture_output=True, text=True,
            ).stdout.strip()
        except Exception:
            new_ver = "?"

        if new_ver == current:
            console.print("[green]Already on the latest version![/green]")
        else:
            console.print(f"[green]Updated: {current} → {new_ver}[/green]")

        # Run doctor
        console.print("\n[dim]Running doctor...[/dim]")
        from trio.cli.doctor_cmd import run_doctor
        await run_doctor(fix=True)
    else:
        console.print(f"[red]Update failed:[/red]\n{result.stderr}")
