"""Session & Context commands (Category.SESSION).

Phase 0 migration scope: /clear (with aliases /new, /reset), preserving the
ANSI screen-clear behavior of the old inline handler.

Phase 2 additions (session-memory): /compact /context /resume /save /load
/export /history /status. These operate on the live SessionManager + MemoryStore
handed in via CommandContext. Where the backing API genuinely supports the
operation the command performs real work; where it needs infrastructure that
does not exist in the REPL yet, the command ships an HONEST message pointing at
the equivalent ``trio`` CLI subcommand rather than faking success.

Everything degrades gracefully: any ctx ref may be None under test/legacy
construction, so each handler guards its dependencies before touching them.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING

from triobot.cli.slash.model import Category, CommandResult
from triobot.cli.slash.registry import command

if TYPE_CHECKING:  # pragma: no cover - typing only
    from triobot.cli.slash.context import CommandContext
    from triobot.core.session import Session

# ANSI: clear screen + move cursor home.
_ANSI_CLEAR = "\033[2J\033[H"

# Rough heuristic: ~4 characters per token for English text. Good enough for a
# ballpark "context size" estimate without pulling in a real tokenizer.
_CHARS_PER_TOKEN = 4

# How many recent messages /compact / /export operate on by default.
_DEFAULT_RECENT = 200


# --------------------------------------------------------------------------- #
# Internal helpers (kept small and dependency-guarded).
# --------------------------------------------------------------------------- #

def _estimate_tokens(messages: list[dict]) -> int:
    """Rough token estimate from message content length (~4 chars/token)."""
    chars = sum(len(str(m.get("content", ""))) for m in messages)
    return chars // _CHARS_PER_TOKEN


def _current_session(ctx: "CommandContext") -> "Session | None":
    """Return the live Session for the CLI key, or None if unavailable."""
    if ctx.sessions is None:
        return None
    try:
        return ctx.sessions.get(ctx.session_key)
    except Exception:
        return None


def _find_named_session(ctx: "CommandContext", name: str) -> dict | None:
    """Look up a persisted session by display name or key (case-insensitive)."""
    if ctx.sessions is None:
        return None
    try:
        entries = ctx.sessions.get_named_sessions()
    except Exception:
        return None
    needle = name.strip().lower()
    for entry in entries:
        if str(entry.get("name", "")).lower() == needle:
            return entry
        if str(entry.get("key", "")).lower() == needle:
            return entry
    return None


def _set_channel_session_label(ctx: "CommandContext", label: str) -> None:
    """Best-effort update of the channel's visible session-name label."""
    channel = ctx.channel
    if channel is None:
        return
    # The CLI channel stores the label on `_session_name`; also honor a public
    # setter if one exists. Never raise on a missing attribute.
    if hasattr(channel, "set_session_name"):
        try:
            channel.set_session_name(label)  # type: ignore[attr-defined]
            return
        except Exception:
            pass
    try:
        setattr(channel, "_session_name", label)
    except Exception:
        pass


# --------------------------------------------------------------------------- #
# /clear  (Phase 0 — unchanged behavior)
# --------------------------------------------------------------------------- #

@command(
    "clear",
    category=Category.SESSION,
    summary="Clear the terminal screen (keeps the session)",
    usage="/clear",
    aliases=("new", "reset"),
)
async def cmd_clear(ctx: "CommandContext", arg: str) -> CommandResult:
    """Clear the terminal. Printed directly so the ANSI codes are emitted raw."""
    print(_ANSI_CLEAR, end="")
    print("trio - chat cleared\n")
    return CommandResult(handled=True)


# --------------------------------------------------------------------------- #
# /compact — summarize the session into MEMORY.md, then trim history.
# --------------------------------------------------------------------------- #

@command(
    "compact",
    category=Category.SESSION,
    summary="Summarize the current session into memory and free up context",
    usage="/compact",
    aliases=("summarize",),
    phase="P2",
)
async def cmd_compact(ctx: "CommandContext", arg: str) -> CommandResult:
    """Consolidate recent messages via ``memory.consolidate`` then trim history.

    Real work when both a MemoryStore and a provider are wired: the summary is
    written to MEMORY.md and the session history is cleared, freeing context.
    Honest no-op messages otherwise (missing deps, too few messages, or a
    provider that could not summarize).
    """
    session = _current_session(ctx)
    if session is None:
        return CommandResult(
            message="[yellow]No active session available to compact.[/yellow]"
        )
    if ctx.memory is None:
        return CommandResult(
            message="[yellow]Memory store not available in this session — cannot compact.[/yellow]"
        )

    before_count = session.message_count
    if before_count == 0:
        return CommandResult(message="[dim]Session is already empty — nothing to compact.[/dim]")

    recent = session.get_recent(_DEFAULT_RECENT)
    before_tokens = _estimate_tokens(recent)

    if ctx.provider is None:
        return CommandResult(
            message=(
                "[yellow]No provider available to summarize the session.[/yellow]\n"
                "Compaction needs an LLM to build the summary. Run inside "
                "'trio agent' with a configured provider, or use 'trio memory' "
                "from the CLI.\n"
            )
        )

    # memory.consolidate returns None when there are <5 messages or the provider
    # summary fails — surface that honestly instead of pretending we compacted.
    summary = None
    try:
        summary = await ctx.memory.consolidate(recent, ctx.provider)
    except Exception as exc:  # never crash the REPL on a provider hiccup
        return CommandResult(message=f"[red]Compaction failed:[/red] {exc}")

    if summary is None:
        return CommandResult(
            message=(
                "[yellow]Nothing consolidated.[/yellow] The session is too short "
                "(needs 5+ messages) or the provider could not summarize it. "
                "History left untouched.\n"
            )
        )

    # Summary persisted to MEMORY.md — now reclaim the session context.
    try:
        session.clear()
        if ctx.sessions is not None:
            ctx.sessions.save_session(session)
    except Exception as exc:
        return CommandResult(
            message=(
                "[green]✓[/green] Summary saved to MEMORY.md, but trimming the "
                f"session history failed: {exc}\n"
            )
        )

    return CommandResult(
        message=(
            "\n[green]✓[/green] Session compacted.\n"
            f"  Summarized [cyan]{before_count}[/cyan] messages into MEMORY.md.\n"
            f"  Freed ~[cyan]{before_tokens}[/cyan] tokens of context.\n"
        )
    )


# --------------------------------------------------------------------------- #
# /context — show current session size + rough token estimate.
# --------------------------------------------------------------------------- #

@command(
    "context",
    category=Category.SESSION,
    summary="Show current session message count and rough token estimate",
    usage="/context",
    phase="P2",
)
async def cmd_context(ctx: "CommandContext", arg: str) -> CommandResult:
    """Report message count and an estimated token footprint for the session."""
    session = _current_session(ctx)
    if session is None:
        return CommandResult(
            message="[yellow]No active session available.[/yellow]"
        )

    count = session.message_count
    tokens = _estimate_tokens(session.history)

    window_line = ""
    if ctx.agent is not None:
        window = getattr(ctx.agent, "memory_window", None)
        if window is not None:
            window_line = f"  Memory window:  [cyan]{window}[/cyan] messages\n"

    return CommandResult(
        message=(
            "\n[bold]Session context[/bold]\n"
            f"  Session:        [cyan]{session.name}[/cyan]\n"
            f"  Messages:       [cyan]{count}[/cyan]\n"
            f"  Est. tokens:    ~[cyan]{tokens}[/cyan] "
            "[dim](rough, ~4 chars/token)[/dim]\n"
            f"{window_line}"
        )
    )


# --------------------------------------------------------------------------- #
# /resume — list named sessions, or switch the active session label.
# --------------------------------------------------------------------------- #

@command(
    "resume",
    category=Category.SESSION,
    summary="List saved sessions, or switch to one by name",
    usage="/resume [name]",
    aliases=("sessions",),
    phase="P2",
)
async def cmd_resume(ctx: "CommandContext", arg: str) -> CommandResult:
    """No-arg: list persisted sessions. With a name: switch the CLI label to it.

    Note: the CLI shares a single fixed session key (``cli:cli_user``), so
    switching updates the visible label and points subsequent /save/export at
    the chosen session. Full multi-session swapping lives in 'trio session'.
    """
    if ctx.sessions is None:
        return CommandResult(
            message="[yellow]Session manager not available.[/yellow]"
        )

    try:
        entries = ctx.sessions.get_named_sessions()
    except Exception as exc:
        return CommandResult(message=f"[red]Could not list sessions:[/red] {exc}")

    if not arg:
        if not entries:
            return CommandResult(
                message="[dim]No saved sessions yet. Use /save <name> to name this one.[/dim]"
            )
        lines = ["\n[bold]Saved sessions[/bold]"]
        for entry in entries:
            name = entry.get("name", entry.get("key", "?"))
            msgs = entry.get("messages", 0)
            lines.append(f"  [green]{name}[/green]  [dim]({msgs} messages)[/dim]")
        lines.append("\n[dim]Switch with: /resume <name>[/dim]\n")
        return CommandResult(message="\n".join(lines))

    match = _find_named_session(ctx, arg)
    if match is None:
        return CommandResult(
            message=(
                f"[yellow]No saved session named[/yellow] '{arg}'. "
                "Run /resume to see available sessions.\n"
            )
        )

    label = str(match.get("name", arg))
    _set_channel_session_label(ctx, label)
    return CommandResult(
        message=(
            f"\n[green]✓[/green] Active session label set to [cyan]{label}[/cyan] "
            f"[dim]({match.get('messages', 0)} messages)[/dim].\n"
            "[dim]The CLI shares one session key; use 'trio session' for full "
            "session swapping.[/dim]\n"
        )
    )


# --------------------------------------------------------------------------- #
# /save — name and persist the current session.
# --------------------------------------------------------------------------- #

@command(
    "save",
    category=Category.SESSION,
    summary="Name and persist the current session",
    usage="/save [name]",
    phase="P2",
)
async def cmd_save(ctx: "CommandContext", arg: str) -> CommandResult:
    """Persist the session file and, if a name is given, set its display name."""
    session = _current_session(ctx)
    if session is None or ctx.sessions is None:
        return CommandResult(
            message="[yellow]Session manager not available — cannot save.[/yellow]"
        )

    # Persist current history to disk (rewrite the JSONL file).
    try:
        ctx.sessions.save_session(session)
    except Exception as exc:
        return CommandResult(message=f"[red]Could not save session:[/red] {exc}")

    name = arg.strip()
    if not name:
        return CommandResult(
            message=(
                f"\n[green]✓[/green] Session saved "
                f"([cyan]{session.message_count}[/cyan] messages).\n"
                "[dim]Give it a name with: /save <name>[/dim]\n"
            )
        )

    renamed = False
    try:
        renamed = bool(ctx.sessions.rename_session(ctx.session_key, name))
    except Exception as exc:
        return CommandResult(
            message=f"[red]Saved history, but naming failed:[/red] {exc}"
        )

    if renamed:
        _set_channel_session_label(ctx, name)
        return CommandResult(
            message=(
                f"\n[green]✓[/green] Session saved as [cyan]{name}[/cyan] "
                f"([cyan]{session.message_count}[/cyan] messages).\n"
            )
        )
    return CommandResult(
        message="[yellow]Session history saved, but the name was not applied.[/yellow]"
    )


# --------------------------------------------------------------------------- #
# /load — load a saved session by name into the CLI view.
# --------------------------------------------------------------------------- #

@command(
    "load",
    category=Category.SESSION,
    summary="Load a saved session by name",
    usage="/load <name>",
    phase="P2",
)
async def cmd_load(ctx: "CommandContext", arg: str) -> CommandResult:
    """Resolve a saved session by name and load it, updating the CLI label."""
    if ctx.sessions is None:
        return CommandResult(
            message="[yellow]Session manager not available — cannot load.[/yellow]"
        )
    if not arg.strip():
        return CommandResult(
            message="[yellow]Usage:[/yellow] /load <name>  (see /resume for the list)"
        )

    match = _find_named_session(ctx, arg)
    if match is None:
        return CommandResult(
            message=(
                f"[yellow]No saved session named[/yellow] '{arg}'. "
                "Run /resume to see available sessions.\n"
            )
        )

    key = str(match.get("key", ""))
    try:
        loaded = ctx.sessions.get(key)
    except Exception as exc:
        return CommandResult(message=f"[red]Could not load session:[/red] {exc}")

    label = str(match.get("name", key))
    _set_channel_session_label(ctx, label)
    return CommandResult(
        message=(
            f"\n[green]✓[/green] Loaded session [cyan]{label}[/cyan] "
            f"([cyan]{loaded.message_count}[/cyan] messages).\n"
            "[dim]The CLI shares one live session key; this sets the visible "
            "label. For full swap-in use 'trio session'.[/dim]\n"
        )
    )


# --------------------------------------------------------------------------- #
# /export — write the conversation to a Markdown file.
# --------------------------------------------------------------------------- #

@command(
    "export",
    category=Category.SESSION,
    summary="Export the conversation to a Markdown file",
    usage="/export [file]",
    phase="P2",
)
async def cmd_export(ctx: "CommandContext", arg: str) -> CommandResult:
    """Write recent messages to a Markdown file (default: cwd/trio-session-*.md)."""
    import time
    from pathlib import Path

    session = _current_session(ctx)
    if session is None:
        return CommandResult(
            message="[yellow]No active session available to export.[/yellow]"
        )

    messages = session.get_recent(_DEFAULT_RECENT)
    if not messages:
        return CommandResult(message="[dim]Session is empty — nothing to export.[/dim]")

    # Resolve the destination path. Default lands in the current directory.
    if arg.strip():
        dest = Path(arg.strip()).expanduser()
        if dest.suffix.lower() != ".md":
            dest = dest.with_suffix(".md")
    else:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe = str(session.name).replace(":", "_").replace("/", "_").replace(" ", "-")
        dest = Path.cwd() / f"trio-session-{safe}-{stamp}.md"

    lines = [
        f"# trio session: {session.name}",
        "",
        f"_Exported {time.strftime('%Y-%m-%d %H:%M:%S')} · {len(messages)} messages_",
        "",
    ]
    for msg in messages:
        role = str(msg.get("role", "unknown")).strip() or "unknown"
        content = str(msg.get("content", "")).rstrip()
        lines.append(f"## {role}")
        lines.append("")
        lines.append(content if content else "_(empty)_")
        lines.append("")

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        return CommandResult(message=f"[red]Could not write export:[/red] {exc}")

    return CommandResult(
        message=(
            f"\n[green]✓[/green] Exported [cyan]{len(messages)}[/cyan] messages to\n"
            f"  [cyan]{dest}[/cyan]\n"
        )
    )


# --------------------------------------------------------------------------- #
# /history — show recent interaction history from HISTORY.md.
# --------------------------------------------------------------------------- #

@command(
    "history",
    category=Category.SESSION,
    summary="Show recent interaction history",
    usage="/history [n]",
    aliases=("log",),
    phase="P2",
)
async def cmd_history(ctx: "CommandContext", arg: str) -> CommandResult:
    """Print the last N lines of HISTORY.md (default 30)."""
    if ctx.memory is None:
        return CommandResult(
            message="[yellow]Memory store not available — no history to show.[/yellow]"
        )

    n = 30
    token = arg.strip().split()[0] if arg.strip() else ""
    if token:
        try:
            n = max(1, int(token))
        except ValueError:
            return CommandResult(
                message=f"[yellow]Not a number:[/yellow] '{token}'. Usage: /history [n]"
            )

    try:
        text = ctx.memory.read_history(n)
    except Exception as exc:
        return CommandResult(message=f"[red]Could not read history:[/red] {exc}")

    if not text or not text.strip():
        return CommandResult(message="[dim]No history recorded yet.[/dim]")

    return CommandResult(
        message=f"\n[bold]Recent history[/bold] [dim](last {n} lines)[/dim]\n{text}\n"
    )


# --------------------------------------------------------------------------- #
# /status — provider, model, session name, message count.
# --------------------------------------------------------------------------- #

@command(
    "status",
    category=Category.SESSION,
    summary="Show provider, model, session name and message count",
    usage="/status",
    phase="P2",
)
async def cmd_status(ctx: "CommandContext", arg: str) -> CommandResult:
    """Summarize the live session state from the CommandContext refs."""
    # Provider + model, preferring live agent state (per-session override), then
    # config defaults, then the provider's own default_model.
    defaults = {}
    if isinstance(ctx.config, dict):
        defaults = ctx.config.get("agents", {}).get("defaults", {})

    provider_name = defaults.get("provider", "unknown")

    model = None
    if ctx.agent is not None:
        try:
            overrides = getattr(ctx.agent, "_user_models", {})
            model = overrides.get(ctx.session_key)
            if model is None:
                model = getattr(ctx.agent, "default_model", None)
        except Exception:
            model = None
    if not model:
        model = defaults.get("model")
    if not model and ctx.provider is not None:
        model = getattr(ctx.provider, "default_model", None)
    model = model or "unknown"

    # Session name + message count.
    session = _current_session(ctx)
    if session is not None:
        session_name = session.name
        message_count = session.message_count
    else:
        session_name = ctx.session_key
        message_count = 0

    return CommandResult(
        message=(
            "\n[bold]trio status[/bold]\n"
            f"  Provider:  [cyan]{provider_name}[/cyan]\n"
            f"  Model:     [cyan]{model}[/cyan]\n"
            f"  Session:   [cyan]{session_name}[/cyan]\n"
            f"  Messages:  [cyan]{message_count}[/cyan]\n"
            "[dim]Full diagnostics: run 'trio status' from the CLI.[/dim]\n"
        )
    )
