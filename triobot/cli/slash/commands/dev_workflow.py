"""Dev Workflow commands (Category.DEV).

Implements the developer-facing REPL commands:

    /plan     toggle the agent's planning mode (propose-before-acting)
    /diff     show `git diff` for the active repo (cwd)
    /commit   draft a conventional-commit message from the staged/working diff
    /init     scaffold a project memory file (TRIO.md) in the cwd
    /memory   show or append to long-term project memory (MEMORY.md)
    /search   search the conversation history log
    /review   honest stub — points at `trio review` / describes planned behavior

Design notes:
    - Git commands are read-only (`git diff`, `git status`). We NEVER run a
      destructive or state-changing git command from the REPL. `/commit` only
      *drafts* a message via the LLM (send_to_llm); it does not auto-commit.
    - Git shell-outs use asyncio.create_subprocess_exec with a fixed argv list
      (NO shell=True, no string interpolation) to avoid shell injection.
    - `/plan` mutates the SAME live `agent._user_modes` dict the agent loop
      reads (loop.py:176), so the toggle is visible on the next turn.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

import asyncio
import pathlib
from typing import TYPE_CHECKING

from triobot.cli.slash.model import Category, CommandResult
from triobot.cli.slash.registry import command

if TYPE_CHECKING:  # pragma: no cover - typing only
    from triobot.cli.slash.context import CommandContext

# Bounds for read-only git shell-outs (mirrors slash/special.py posture).
_GIT_TIMEOUT_SECONDS = 30
_MAX_GIT_OUTPUT_CHARS = 8000

# Name of the project memory / agent-instructions file created by /init.
_PROJECT_MEMORY_FILE = "TRIO.md"

# Plan mode is stored in agent._user_modes under this value; the agent loop
# treats "reasoning" as the propose-before-acting / deep-reasoning mode
# (loop.py:210 builds a ThinkTagParser for mode == "reasoning").
_PLAN_MODE = "reasoning"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #
async def _run_git(*args: str) -> tuple[bool, str]:
    """Run a read-only git command safely (no shell=True).

    Returns (ok, output). `ok` is False on non-zero exit, missing git, timeout,
    or OS error; `output` always carries a human-readable body.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
    except FileNotFoundError:
        return False, "git is not installed or not on PATH."
    except OSError as e:  # pragma: no cover - environment dependent
        return False, f"Failed to launch git: {e}"

    try:
        out, _ = await asyncio.wait_for(
            proc.communicate(), timeout=_GIT_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:  # pragma: no cover - environment dependent
        proc.kill()
        return False, f"git timed out after {_GIT_TIMEOUT_SECONDS}s."

    text = out.decode(errors="replace")
    if len(text) > _MAX_GIT_OUTPUT_CHARS:
        text = text[:_MAX_GIT_OUTPUT_CHARS] + "\n... (truncated)"
    ok = proc.returncode == 0
    return ok, text


def _project_memory_template() -> str:
    """AGENTS.md-style template written by /init when TRIO.md is absent."""
    return (
        "# TRIO.md\n\n"
        "> Project memory & agent instructions for triobot. This file is read\n"
        "> as long-term context for this project. Keep it concise and current.\n\n"
        "## Project\n\n"
        "- **Name:** \n"
        "- **Purpose:** \n"
        "- **Stack:** \n\n"
        "## Conventions\n\n"
        "- Coding style: \n"
        "- Commit style: conventional commits (feat, fix, refactor, docs, ...)\n"
        "- Testing: \n\n"
        "## Commands\n\n"
        "- Build: \n"
        "- Test: \n"
        "- Run: \n\n"
        "## Notes for the agent\n\n"
        "- \n"
    )


# --------------------------------------------------------------------------- #
# /plan
# --------------------------------------------------------------------------- #
@command(
    "plan",
    category=Category.DEV,
    summary="Toggle planning mode (agent proposes before acting)",
    usage="/plan [off]",
    phase="P2",
)
async def cmd_plan(ctx: "CommandContext", arg: str) -> CommandResult:
    """Enter or leave plan mode by setting agent._user_modes[session_key].

    Plan mode switches the agent into its reasoning/propose-before-acting mode:
    the next turns think through an approach and lay out steps before taking
    action, instead of jumping straight to edits. `/plan off` clears the
    override so the agent returns to its default mode.
    """
    agent = getattr(ctx, "agent", None)
    if agent is None or getattr(agent, "_user_modes", None) is None:
        return CommandResult(
            message=(
                "[yellow]Plan mode is unavailable[/yellow] — the agent is not "
                "wired into this session."
            )
        )

    key = ctx.session_key

    if arg.strip().lower() in ("off", "clear", "exit", "stop"):
        agent._user_modes.pop(key, None)
        return CommandResult(
            message=(
                "\n[green]Plan mode OFF[/green] — back to the default mode. "
                "The agent will act directly again.\n"
            )
        )

    agent._user_modes[key] = _PLAN_MODE
    return CommandResult(
        message=(
            "\n[green]Plan mode ON[/green]\n"
            "The agent will now [bold]think through an approach and propose a "
            "step-by-step plan before acting[/bold], rather than jumping "
            "straight to changes. Review the plan, then continue the "
            "conversation to have it executed.\n"
            "Turn it off with: [cyan]/plan off[/cyan]\n"
        )
    )


# --------------------------------------------------------------------------- #
# /diff
# --------------------------------------------------------------------------- #
@command(
    "diff",
    category=Category.DEV,
    summary="Show `git diff` for the current repo",
    usage="/diff [args]",
    phase="P2",
)
async def cmd_diff(ctx: "CommandContext", arg: str) -> CommandResult:
    """Run a read-only `git diff` in the cwd and show the output.

    Extra args are passed through as literal, pre-tokenized arguments (e.g.
    `/diff --staged` or `/diff HEAD~1`). Arguments are split on whitespace
    only; no shell is involved.
    """
    extra = arg.split() if arg.strip() else []
    ok, out = await _run_git("diff", *extra)

    if not ok:
        return CommandResult(message=f"[red]git diff failed:[/red]\n{out}")

    body = out.strip()
    if not body:
        return CommandResult(
            message="[dim]No changes — `git diff` is empty (working tree clean).[/dim]"
        )
    return CommandResult(message=f"[dim]$ git diff {' '.join(extra)}[/dim]\n{body}")


# --------------------------------------------------------------------------- #
# /commit
# --------------------------------------------------------------------------- #
@command(
    "commit",
    category=Category.DEV,
    summary="Draft a conventional-commit message from the diff (no auto-commit)",
    usage="/commit",
    phase="P2",
)
async def cmd_commit(ctx: "CommandContext", arg: str) -> CommandResult:
    """Gather git status + staged diff, then ask the model to draft a message.

    This NEVER commits. It collects context read-only and routes a prompt to
    the LLM via `send_to_llm`; the user copies/edits the suggestion and commits
    themselves.
    """
    status_ok, status = await _run_git("status", "--short")
    staged_ok, staged = await _run_git("diff", "--staged")

    if not status_ok and not staged_ok:
        return CommandResult(
            message=(
                "[red]Could not read git state.[/red] "
                f"{status}"
            )
        )

    staged_body = staged.strip()
    status_body = status.strip()

    if not staged_body:
        note = (
            "\n[yellow]No staged changes[/yellow] — nothing is staged to commit.\n"
            "Stage files first (e.g. [cyan]!git add -p[/cyan]), then run "
            "[cyan]/commit[/cyan] again.\n"
        )
        if not status_body:
            note += "[dim](working tree is clean)[/dim]\n"
        return CommandResult(message=note)

    prompt = (
        "You are drafting a git commit message. Based ONLY on the changes "
        "below, write a single Conventional Commit message.\n\n"
        "Rules:\n"
        "- First line: `<type>: <concise summary>` (<=72 chars). Types: feat, "
        "fix, refactor, docs, test, chore, perf, ci.\n"
        "- Then a blank line, then an optional short body explaining the WHY.\n"
        "- Do NOT invent changes that are not in the diff.\n"
        "- Output ONLY the commit message, no surrounding commentary.\n\n"
        f"--- git status --short ---\n{status_body or '(no status output)'}\n\n"
        f"--- git diff --staged ---\n{staged_body}\n"
    )

    return CommandResult(
        message=(
            "[dim]Drafting a conventional-commit message from your staged "
            "changes (nothing will be committed)...[/dim]"
        ),
        handled=True,
        send_to_llm=prompt,
    )


# --------------------------------------------------------------------------- #
# /init
# --------------------------------------------------------------------------- #
@command(
    "init",
    category=Category.DEV,
    summary="Create a project memory file (TRIO.md) in the current directory",
    usage="/init",
    phase="P2",
)
async def cmd_init(ctx: "CommandContext", arg: str) -> CommandResult:
    """Create an AGENTS.md-style TRIO.md in the cwd if it does not already exist."""
    try:
        target = (pathlib.Path.cwd() / _PROJECT_MEMORY_FILE).resolve()
    except OSError as e:  # pragma: no cover - environment dependent
        return CommandResult(message=f"[red]Could not resolve cwd:[/red] {e}")

    if target.exists():
        return CommandResult(
            message=(
                f"[yellow]{_PROJECT_MEMORY_FILE} already exists[/yellow] at "
                f"[cyan]{target}[/cyan] — leaving it untouched.\n"
            )
        )

    try:
        target.write_text(_project_memory_template(), encoding="utf-8")
    except OSError as e:
        return CommandResult(
            message=f"[red]Failed to create {_PROJECT_MEMORY_FILE}:[/red] {e}"
        )

    return CommandResult(
        message=(
            f"\n[green]Created[/green] project memory file: [cyan]{target}[/cyan]\n"
            "Fill in the project details and conventions — it becomes long-term "
            "context for this project.\n"
        )
    )


# --------------------------------------------------------------------------- #
# /memory  (alias /project)
# --------------------------------------------------------------------------- #
@command(
    "memory",
    category=Category.DEV,
    summary="Show project memory, or append a fact with `/memory <fact>`",
    usage="/memory [fact]",
    aliases=("project",),
    phase="P2",
)
async def cmd_memory(ctx: "CommandContext", arg: str) -> CommandResult:
    """No-arg: show MEMORY.md. With an arg: append it as a long-term fact."""
    memory = getattr(ctx, "memory", None)
    if memory is None:
        return CommandResult(
            message="[yellow]Memory is unavailable in this session.[/yellow]"
        )

    fact = arg.strip()
    if fact:
        memory.save_memory_fact(fact)
        return CommandResult(
            message=f"\n[green]Remembered[/green]: {fact}\n"
        )

    contents = memory.read_memory().strip()
    if not contents:
        return CommandResult(
            message=(
                "[dim]Project memory is empty.[/dim] "
                "Add a fact with: [cyan]/memory <fact>[/cyan]\n"
            )
        )
    return CommandResult(message=f"\n[bold]Project memory[/bold]\n\n{contents}\n")


# --------------------------------------------------------------------------- #
# /search
# --------------------------------------------------------------------------- #
@command(
    "search",
    category=Category.DEV,
    summary="Search the conversation history log",
    usage="/search <query>",
    phase="P2",
)
async def cmd_search(ctx: "CommandContext", arg: str) -> CommandResult:
    """Search HISTORY.md via memory.search_history(query)."""
    memory = getattr(ctx, "memory", None)
    if memory is None:
        return CommandResult(
            message="[yellow]History search is unavailable in this session.[/yellow]"
        )

    query = arg.strip()
    if not query:
        return CommandResult(
            message="[yellow]Usage:[/yellow] /search <query>  e.g. /search deployment"
        )

    results = memory.search_history(query)
    if not results:
        return CommandResult(
            message=f"[dim]No history matches for[/dim] [cyan]{query}[/cyan]."
        )

    lines = [f"\n[bold]History matches for[/bold] [cyan]{query}[/cyan]:\n"]
    lines.extend(f"  {line}" for line in results)
    return CommandResult(message="\n".join(lines) + "\n")


# --------------------------------------------------------------------------- #
# /review  (honest stub)
# --------------------------------------------------------------------------- #
@command(
    "review",
    category=Category.DEV,
    summary="Code review of the current diff (not yet available in the REPL)",
    usage="/review",
    phase="P4",
)
async def cmd_review(ctx: "CommandContext", arg: str) -> CommandResult:
    """Honest stub — an in-REPL review pipeline is not wired yet.

    Rather than faking a review, point the user at the real CLI entry point and
    describe the planned behavior so /help stays truthful.
    """
    return CommandResult(
        message=(
            "\n[yellow]/review is not available in the chat REPL yet.[/yellow]\n\n"
            "Today, run a review from your shell:\n"
            "  [cyan]trio review[/cyan]        review the current changes\n"
            "  (or [cyan]!git diff[/cyan] here, then ask me to review the output)\n\n"
            "[dim]Planned:[/dim] /review will collect `git diff` and route it to "
            "the model for an inline, structured code review (correctness, "
            "security, and style) without leaving the chat.\n"
        )
    )
