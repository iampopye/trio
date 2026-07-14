"""triobot-native commands (Category.NATIVE).

These are the commands triobot's competitors (Claude Code / Codex / OpenCode)
do NOT have — they wrap trio's own multi-channel, model-tier, hub, daemon,
pairing, and training surfaces.

Two shapes live here:

1. In-process, returns-quickly actions (config toggles, status/list reads):
   ``/tier``, ``/channel``, ``/daemon status``, ``/hub``, ``/pairing`` — these
   run directly (config mutation via ``save_config`` or a thin call into the
   existing ``run_*`` runner) and hand back a ``CommandResult``.

2. Long-running or interactive processes: ``/serve``, ``/gateway``, ``/train``,
   ``/onboard`` (and the non-``status`` daemon actions) — these MUST NEVER block
   the REPL. They print clear guidance to run the corresponding ``trio <cmd>`` in
   a separate terminal instead of launching in-process.

Every handler is wrapped so a bad argument or a runner hiccup returns a
``CommandResult`` rather than crashing the interactive loop.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

from triobot.cli.slash.model import Category, CommandResult
from triobot.cli.slash.registry import command

if TYPE_CHECKING:  # pragma: no cover - typing only
    from triobot.cli.slash.context import CommandContext


# ── /tier ──────────────────────────────────────────────────────────────────


@command(
    "tier",
    category=Category.NATIVE,
    summary="Show or set the active model (models are provider-defined)",
    usage="/tier [model-name]",
    aliases=("tiers",),
)
async def cmd_tier(ctx: "CommandContext", arg: str) -> CommandResult:
    """Show or set the active model.

    triobot no longer ships fixed model "tiers" — it is provider-agnostic, so
    the model is whatever your configured provider serves (an Ollama model, a
    local GGUF, or an API model). This is a thin alias of ``/model``: with no
    argument it shows the current model and points at ``/models``; with an
    argument it persists that model name. Takes effect on the next
    ``trio agent`` launch.
    """
    from triobot.core.config import load_config, save_config

    cfg = load_config()
    current = cfg.get("agents", {}).get("defaults", {}).get("model") or "(not set)"

    if not arg:
        return CommandResult(
            message=(
                f"\nCurrent model: [cyan]{current}[/cyan]\n"
                "[dim]triobot is provider-agnostic — there are no fixed tiers.[/dim]\n"
                "List what your provider offers with [green]/models[/green], "
                "then set one with [green]/model <name>[/green] or /tier <name>.\n"
            )
        )

    new_model = arg.strip()
    cfg.setdefault("agents", {}).setdefault("defaults", {})["model"] = new_model
    save_config(cfg)
    return CommandResult(
        message=(
            f"\n[green]OK[/green] Model set to: [cyan]{new_model}[/cyan]\n"
            "Restart 'trio agent' for the change to take effect.\n"
        )
    )


# ── /channel ───────────────────────────────────────────────────────────────


@command(
    "channel",
    category=Category.NATIVE,
    summary="List channels or toggle one on/off",
    usage="/channel [name [on|off]]",
    aliases=("channels",),
)
async def cmd_channel(ctx: "CommandContext", arg: str) -> CommandResult:
    """List channels and their enabled state, or toggle one in config.

    ``/channel``            — list every channel and whether it is enabled.
    ``/channel <name>``     — show that channel's state.
    ``/channel <name> on``  — enable it and persist via ``save_config``.
    ``/channel <name> off`` — disable it and persist via ``save_config``.

    Config-only: enabling a channel here takes effect when the gateway is
    (re)started — this command never launches the gateway itself.
    """
    from triobot.core.config import load_config, save_config

    cfg = load_config()
    channels = cfg.get("channels", {})

    if not channels:
        return CommandResult(message="\n[yellow]No channels configured.[/yellow]\n")

    parts = arg.split()

    # No argument -> list all channels + state.
    if not parts:
        rows = []
        for name in sorted(channels):
            entry = channels.get(name) or {}
            enabled = bool(entry.get("enabled", False)) if isinstance(entry, dict) else False
            state = "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]"
            rows.append(f"  [cyan]{name:<14}[/cyan] {state}")
        return CommandResult(
            message=(
                "\n[bold]Channels[/bold]:\n"
                + "\n".join(rows)
                + "\n\nToggle with: /channel <name> on|off\n"
            )
        )

    name = parts[0].lower()
    if name not in channels:
        available = ", ".join(sorted(channels))
        return CommandResult(
            message=(
                f"\n[red]Unknown channel:[/red] {name}\n"
                f"Available: {available}\n"
            )
        )

    entry = channels.get(name)
    if not isinstance(entry, dict):
        return CommandResult(
            message=f"\n[red]Channel '{name}' has an unexpected config shape.[/red]\n"
        )

    # /channel <name> -> show state only.
    if len(parts) == 1:
        enabled = bool(entry.get("enabled", False))
        state = "[green]enabled[/green]" if enabled else "[dim]disabled[/dim]"
        return CommandResult(
            message=(
                f"\nChannel [cyan]{name}[/cyan]: {state}\n"
                "Toggle with: /channel <name> on|off\n"
            )
        )

    # /channel <name> on|off -> toggle + persist.
    toggle = parts[1].lower()
    if toggle not in ("on", "off"):
        return CommandResult(
            message=(
                f"\n[yellow]Usage:[/yellow] /channel {name} on|off\n"
            )
        )

    new_state = toggle == "on"
    # Immutable-friendly update: build a fresh channel entry, don't mutate the
    # loaded dict's nested object in place before persisting.
    updated_entry = dict(entry)
    updated_entry["enabled"] = new_state
    cfg.setdefault("channels", {})[name] = updated_entry
    save_config(cfg)

    verb = "enabled" if new_state else "disabled"
    return CommandResult(
        message=(
            f"\n[green]OK[/green] Channel [cyan]{name}[/cyan] {verb}.\n"
            "Restart 'trio gateway' for the change to take effect.\n"
        )
    )


# ── /hub ───────────────────────────────────────────────────────────────────


@command(
    "hub",
    category=Category.NATIVE,
    summary="Browse the TrioHub skills/plugins registry",
    usage="/hub [query]",
)
async def cmd_hub(ctx: "CommandContext", arg: str) -> CommandResult:
    """Browse TrioHub — wraps ``trio hub search/trending``.

    ``/hub`` (no arg) shows trending items; ``/hub <query>`` searches. Both are
    quick network reads that print via the runner's own console, so this returns
    an empty handled result to avoid double output. Errors never crash the REPL.
    """
    from triobot.cli.hub_cmd import run_hub

    query = arg.strip()
    if query:
        args = SimpleNamespace(hub_action="search", query=query)
    else:
        args = SimpleNamespace(hub_action="trending")

    try:
        await run_hub(args)
    except Exception as e:  # network / registry hiccup — stay in the REPL
        return CommandResult(
            message=(
                f"\n[yellow]Could not reach TrioHub:[/yellow] {e}\n"
                "Try from a terminal: [green]trio hub search <query>[/green] "
                "or [green]trio hub trending[/green]\n"
            )
        )
    return CommandResult(handled=True)


# ── /onboard ───────────────────────────────────────────────────────────────


@command(
    "onboard",
    category=Category.NATIVE,
    summary="Re-run interactive onboarding (in a separate terminal)",
    usage="/onboard",
)
async def cmd_onboard(ctx: "CommandContext", arg: str) -> CommandResult:
    """Onboarding is interactive (prompts for provider/keys), so it cannot run
    inside the REPL prompt without blocking. Print guidance to run it in a
    separate terminal.
    """
    return CommandResult(
        message=(
            "\n[bold]Re-run onboarding[/bold]\n"
            "Onboarding is interactive, so run it from a separate terminal:\n\n"
            "  [green]trio onboard[/green]    initialize config + workspace, pick a provider\n"
        )
    )


# ── /serve ─────────────────────────────────────────────────────────────────


@command(
    "serve",
    category=Category.NATIVE,
    summary="How to launch the browser-based web UI",
    usage="/serve",
)
async def cmd_serve(ctx: "CommandContext", arg: str) -> CommandResult:
    """The web UI is a long-running server; launching it here would block the
    REPL. Print guidance to run it in a separate terminal.
    """
    return CommandResult(
        message=(
            "\n[bold]Web UI[/bold]\n"
            "'trio serve' runs a long-lived server, so start it in a separate terminal:\n\n"
            "  [green]trio serve[/green]                      start on http://127.0.0.1:28337\n"
            "  [green]trio serve --port 9000[/green]          use a custom port\n"
            "  [green]trio serve --host 0.0.0.0[/green]       bind all interfaces\n\n"
            "[dim]Keep this chat session running; the web UI is independent.[/dim]\n"
        )
    )


# ── /gateway ───────────────────────────────────────────────────────────────


@command(
    "gateway",
    category=Category.NATIVE,
    summary="How to start all enabled channels",
    usage="/gateway",
)
async def cmd_gateway(ctx: "CommandContext", arg: str) -> CommandResult:
    """The gateway runs all enabled channels as long-lived listeners; launching
    it here would block the REPL. Print guidance plus the current enabled set so
    the user knows what will start.
    """
    from triobot.core.config import load_config

    cfg = load_config()
    channels = cfg.get("channels", {})
    enabled = sorted(
        name
        for name, entry in channels.items()
        if isinstance(entry, dict) and entry.get("enabled", False)
    )
    enabled_line = ", ".join(enabled) if enabled else "(none — enable with /channel <name> on)"

    return CommandResult(
        message=(
            "\n[bold]Channel gateway[/bold]\n"
            "'trio gateway' runs long-lived channel listeners, so start it in a "
            "separate terminal:\n\n"
            "  [green]trio gateway[/green]    start all enabled channels\n\n"
            f"Currently enabled: [cyan]{enabled_line}[/cyan]\n"
        )
    )


# ── /daemon ────────────────────────────────────────────────────────────────


@command(
    "daemon",
    category=Category.NATIVE,
    summary="Show daemon status or how to control it",
    usage="/daemon [status|start|stop|restart]",
)
async def cmd_daemon(ctx: "CommandContext", arg: str) -> CommandResult:
    """Background gateway daemon control.

    ``/daemon`` / ``/daemon status`` runs the quick, in-process status read via
    ``run_daemon("status")``. The lifecycle actions (start/stop/restart) spawn or
    signal a detached background process — to keep behavior single-sourced and
    the REPL responsive, they print guidance to run ``trio daemon <action>`` in a
    separate terminal rather than doing it in-process.
    """
    action = arg.strip().lower()

    if action in ("", "status"):
        from triobot.cli.daemon_cmd import run_daemon

        try:
            await run_daemon("status")  # prints its own status table
        except Exception as e:  # never crash the REPL on a status hiccup
            return CommandResult(
                message=f"\n[yellow]Could not read daemon status:[/yellow] {e}\n"
            )
        return CommandResult(handled=True)

    if action in ("start", "stop", "restart"):
        return CommandResult(
            message=(
                f"\n[bold]Daemon {action}[/bold]\n"
                f"'trio daemon {action}' manages a detached background process; run it "
                "from a separate terminal:\n\n"
                f"  [green]trio daemon {action}[/green]\n\n"
                "[dim]Quick check any time with: /daemon status[/dim]\n"
            )
        )

    return CommandResult(
        message=(
            f"\n[yellow]Unknown daemon action:[/yellow] {action}\n"
            "Usage: /daemon [status|start|stop|restart]\n"
            "[dim]Full control (install/uninstall/logs): trio daemon <action>[/dim]\n"
        )
    )


# ── /train ─────────────────────────────────────────────────────────────────


@command(
    "train",
    category=Category.NATIVE,
    summary="How to train the from-scratch trio model (experimental)",
    usage="/train",
)
async def cmd_train(ctx: "CommandContext", arg: str) -> CommandResult:
    """Training is a long-running, interactive pipeline (progress, Ctrl+C to
    pause/resume). Launching it here would block the REPL, so print guidance to
    run it in a separate terminal.
    """
    return CommandResult(
        message=(
            "\n[bold]Train the from-scratch trio model[/bold] [dim](experimental)[/dim]\n"
            "This trains a genuine model from scratch via the local pipeline — "
            "it is long-running, so start it in a separate terminal:\n\n"
            "  [green]trio train[/green]           start or resume training (pause/resume with Ctrl+C)\n"
            "  [green]trio train --reset[/green]   start fresh, ignore saved progress\n\n"
            "[dim]To run an existing model instead, configure a provider with "
            "'trio onboard' (e.g. Ollama).[/dim]\n"
        )
    )


# ── /pairing ───────────────────────────────────────────────────────────────


@command(
    "pairing",
    category=Category.NATIVE,
    summary="Show DM pairing status across channels",
    usage="/pairing",
)
async def cmd_pairing(ctx: "CommandContext", arg: str) -> CommandResult:
    """DM pairing management — wraps ``trio pairing list``.

    Shows the pending/approved pairing status per channel (a quick, in-process
    read that prints via the runner's own console). Approve/revoke require
    channel + code/user arguments best done from the CLI, so this points there.
    """
    from triobot.cli.pairing_cmd import run_pairing

    action = arg.strip().lower()

    if action in ("", "list"):
        args = SimpleNamespace(pairing_action="list")
        try:
            await run_pairing(args)  # prints its own status table
        except Exception as e:  # never crash the REPL
            return CommandResult(
                message=f"\n[yellow]Could not read pairing status:[/yellow] {e}\n"
            )
        return CommandResult(handled=True)

    if action == "pending":
        args = SimpleNamespace(pairing_action="pending")
        try:
            await run_pairing(args)
        except Exception as e:
            return CommandResult(
                message=f"\n[yellow]Could not read pending pairings:[/yellow] {e}\n"
            )
        return CommandResult(handled=True)

    return CommandResult(
        message=(
            "\n[bold]DM pairing[/bold]\n"
            "  [green]/pairing[/green]           show pairing status (pending + approved)\n"
            "  [green]/pairing pending[/green]   show pending requests\n\n"
            "Approve or revoke from a terminal (needs channel + code/user):\n"
            "  [green]trio pairing approve <channel> <code>[/green]\n"
            "  [green]trio pairing revoke <channel> <user_id>[/green]\n"
        )
    )
