"""Special syntax: `!shell` command execution and `@file` inlining.

Security posture (security.md):
    - !shell prefers the registered, policy-guarded ShellTool when present so
      the restrictToWorkspace guard and future approval policy apply. The direct
      fallback uses asyncio.create_subprocess_exec with shlex.split — NO
      shell=True, no string interpolation into a shell — to avoid injection.
    - @file resolves each path under the workspace or cwd and rejects anything
      that escapes both roots (path-traversal guard). File content is capped at
      MAX_FILE_BYTES and decoded with errors="replace" so a binary reference
      never crashes the REPL.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

import asyncio
import pathlib
import re
import shlex
from typing import TYPE_CHECKING

from triobot.cli.slash.model import CommandResult
from triobot.core.config import get_workspace_dir

if TYPE_CHECKING:  # pragma: no cover - typing only
    from triobot.cli.slash.context import CommandContext

# One or more @path tokens inside an otherwise-normal line.
AT_TOKEN = re.compile(r"@([^\s]+)")
# Cap inlined file content to keep prompts bounded.
MAX_FILE_BYTES = 100_000
# Fallback-subprocess bounds (the guarded ShellTool has its own limits).
SHELL_TIMEOUT_SECONDS = 30
MAX_SHELL_OUTPUT_CHARS = 4000


async def handle_shell(cmd: str, ctx: "CommandContext") -> CommandResult:
    """Run a shell command locally. Never reaches the LLM.

    Prefers the registered ShellTool (policy-guarded); otherwise falls back to a
    safe subprocess_exec with shlex.split (no shell=True).
    """
    cmd = cmd.strip()
    if not cmd:
        return CommandResult(
            message="[yellow]Usage:[/yellow] !<command>  e.g. !git status"
        )

    # Prefer the registered, policy-guarded shell tool if present.
    tools = getattr(ctx, "tools", None)
    if tools is not None and "shell" in tools.list_tools():
        res = await tools.execute("shell", {"command": cmd})
        body = res.output if res.success else f"[red]{res.output}[/red]"
        return CommandResult(message=f"[dim]$ {cmd}[/dim]\n{body}")

    # Fallback: direct subprocess (no shell=True; split safely).
    try:
        argv = shlex.split(cmd)
    except ValueError as e:
        return CommandResult(message=f"[red]Bad command syntax:[/red] {e}")
    if not argv:
        return CommandResult(
            message="[yellow]Usage:[/yellow] !<command>  e.g. !git status"
        )

    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            out, _ = await asyncio.wait_for(
                proc.communicate(), timeout=SHELL_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            proc.kill()
            return CommandResult(
                message=f"[red]Command timed out after {SHELL_TIMEOUT_SECONDS}s:[/red] {cmd}"
            )
        text = out.decode(errors="replace")
        if len(text) > MAX_SHELL_OUTPUT_CHARS:
            text = text[:MAX_SHELL_OUTPUT_CHARS] + "\n... (truncated)"
        return CommandResult(message=f"[dim]$ {cmd}[/dim]\n{text}")
    except FileNotFoundError:
        return CommandResult(message=f"[red]Command not found:[/red] {argv[0]}")
    except OSError as e:
        return CommandResult(message=f"[red]Command failed:[/red] {e}")


def _roots() -> list[pathlib.Path]:
    """Return the allowed root directories for @file resolution."""
    roots: list[pathlib.Path] = []
    try:
        roots.append(get_workspace_dir().resolve())
    except OSError:
        pass
    try:
        roots.append(pathlib.Path.cwd().resolve())
    except OSError:
        pass
    return roots


def _resolve_under_roots(raw: str, roots: list[pathlib.Path]) -> pathlib.Path | None:
    """Resolve `raw` to a file that lives under one of `roots`, else None."""
    for root in roots:
        candidate = (root / raw).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            continue  # escapes this root — path-traversal guard
        if candidate.is_file():
            return candidate
    return None


async def expand_at_file(text: str, ctx: "CommandContext") -> str | None:
    """Replace each @path token with a fenced block of that file's content.

    Returns the rewritten text, or None if nothing was expanded (no matches, no
    readable/allowed files). A @ that resolves to no in-bounds file is left
    untouched (could be an email address, decorator, etc.).
    """
    matches = list(AT_TOKEN.finditer(text))
    if not matches:
        return None

    roots = _roots()
    if not roots:
        return None

    blocks: list[str] = []
    for m in matches:
        raw = m.group(1)
        path = _resolve_under_roots(raw, roots)
        if path is None:
            continue  # not a file, or traversal outside every root
        # Read at most MAX_FILE_BYTES — never pull a huge/special file into RAM.
        try:
            with path.open("rb") as fh:
                data = fh.read(MAX_FILE_BYTES)
        except OSError:
            continue  # unreadable (permissions, special file) — skip silently
        blocks.append(
            f"\n\n--- {raw} ---\n```\n{data.decode(errors='replace')}\n```"
        )

    if not blocks:
        return None
    return text + "".join(blocks)
