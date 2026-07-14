"""Auto-generated /help, driven entirely by registry metadata.

A newly registered command appears automatically — there is nothing to update
here when commands are added.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

from triobot.cli.slash.model import Category
from triobot.cli.slash.registry import CANONICAL

# Column width for the usage string in the help table.
_USAGE_COL = 26


def render_help(category: str | None = None) -> str:
    """Render the grouped slash-command help table.

    Args:
        category: Optional case-insensitive substring; only categories whose
            display name contains it are shown (e.g. "model" → Model & Provider).
    """
    lines = ["", "[bold]triobot slash commands[/bold]", ""]
    for cat in Category:  # stable enum order
        if category and category.lower() not in cat.value.lower():
            continue
        cmds = [c for c in CANONICAL if c.category is cat]
        if not cmds:
            continue
        lines.append(f"[bold cyan]{cat.value}[/bold cyan]")
        for c in sorted(cmds, key=lambda x: x.name):
            alias = (
                f"  ([dim]{', '.join('/' + a for a in c.aliases)}[/dim])"
                if c.aliases
                else ""
            )
            lines.append(
                f"  [green]{c.usage:<{_USAGE_COL}}[/green] {c.summary}{alias}"
            )
        lines.append("")
    lines.append(
        "[dim]!<cmd> runs a shell command · @path/to/file inlines a file · "
        "run `trio help` for CLI reference[/dim]"
    )
    return "\n".join(lines)
