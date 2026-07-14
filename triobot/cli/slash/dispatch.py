"""dispatch(line, ctx) — the single entry point the channel calls.

Handles three special forms and normal chat:
    1. !shell escape (highest precedence)
    2. /verb slash commands (unknown /foo returns handled=False so it still
       falls through to the LLM, preserving today's behavior)
    3. @file expansion inside otherwise-normal input
    4. everything else → handled=False (normal chat, channel sends to LLM)

`handled=False` means "channel should send this to the LLM". `send_to_llm`
lets @file rewrite the outgoing text while still routing through the LLM path.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING

from triobot.cli.slash.model import CommandResult
from triobot.cli.slash.registry import resolve
from triobot.cli.slash.special import expand_at_file, handle_shell

if TYPE_CHECKING:  # pragma: no cover - typing only
    from triobot.cli.slash.context import CommandContext


async def dispatch(line: str, ctx: "CommandContext") -> CommandResult:
    """Route a single input line. Never raises — bad commands are caught."""
    stripped = line.strip()

    # 1. !shell escape (highest precedence, OpenCode-style).
    if stripped.startswith("!"):
        return await handle_shell(stripped[1:].strip(), ctx)

    # 2. Slash command.
    if stripped.startswith("/"):
        parts = stripped[1:].split(maxsplit=1)
        if not parts or not parts[0]:
            return CommandResult(handled=False)  # bare "/" → normal input
        verb = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""
        cmd = resolve(verb)
        if cmd is None:
            # Unknown slash → not handled; channel falls through to the LLM.
            return CommandResult(handled=False)
        try:
            return await cmd.handler(ctx, arg)
        except Exception as e:  # never crash the REPL on a bad command
            return CommandResult(message=f"[red]Command /{verb} failed:[/red] {e}")

    # 3. @file expansion inside otherwise-normal input → prompt for the LLM.
    if "@" in stripped:
        try:
            expanded = await expand_at_file(stripped, ctx)
        except Exception:
            expanded = None
        if expanded is not None and expanded != stripped:
            return CommandResult(handled=False, send_to_llm=expanded)

    # 4. Normal chat input.
    return CommandResult(handled=False)
