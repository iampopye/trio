"""Model & Provider commands (Category.MODEL).

Phase 0 migration scope: /provider and /model, preserving the config-based
logic of the old _slash_provider / _slash_model methods.

Phase 2 additions (this file):
    /models    list models available from the current provider
    /connect   guide adding a provider + API key (wraps `trio provider add`)
    /effort    show or set reasoning effort (minimal/low/medium/high)
    /fast      show or toggle fast mode
    /thinking  show or toggle visible reasoning (deepthink)
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING

from triobot.cli.slash.model import Category, CommandResult
from triobot.cli.slash.registry import command

if TYPE_CHECKING:  # pragma: no cover - typing only
    from triobot.cli.slash.context import CommandContext

_PROVIDERS = "ollama, local, openai, anthropic, gemini, groq, deepseek, openrouter, github_models"
# Accepted reasoning-effort levels (ordered least → most).
_EFFORT_LEVELS = ("minimal", "low", "medium", "high")


@command(
    "provider",
    category=Category.MODEL,
    summary="Show or switch the default provider",
    usage="/provider [name]",
    aliases=("providers",),
)
async def cmd_provider(ctx: "CommandContext", arg: str) -> CommandResult:
    """Show the current provider or persist a switch (takes effect on restart)."""
    from triobot.core.config import load_config, save_config

    cfg = load_config()
    current = cfg.get("agents", {}).get("defaults", {}).get("provider", "ollama")

    if not arg:
        return CommandResult(
            message=(
                f"\nCurrent provider: [cyan]{current}[/cyan]\n"
                f"Available: {_PROVIDERS}\n"
                "Switch with: /provider <name>\n"
            )
        )

    new_provider = arg.lower().strip()
    cfg.setdefault("agents", {}).setdefault("defaults", {})["provider"] = new_provider
    save_config(cfg)
    return CommandResult(
        message=(
            f"\n[green]✓[/green] Provider switched to: [cyan]{new_provider}[/cyan]\n"
            "Restart 'trio agent' for the change to take effect.\n"
        )
    )


@command(
    "model",
    category=Category.MODEL,
    summary="Show or switch the default model",
    usage="/model [name]",
    aliases=("setmodel",),
)
async def cmd_model(ctx: "CommandContext", arg: str) -> CommandResult:
    """Show the current model or persist a switch (takes effect on restart)."""
    from triobot.core.config import load_config, save_config

    cfg = load_config()
    current = cfg.get("agents", {}).get("defaults", {}).get("model") or "(not set)"

    if not arg:
        return CommandResult(
            message=(
                f"\nCurrent model: [cyan]{current}[/cyan]\n"
                "[dim]Models are provider-defined.[/dim] "
                "List what your provider offers with [green]/models[/green].\n"
                "Switch with: /model <name>\n"
            )
        )

    new_model = arg.strip()
    cfg.setdefault("agents", {}).setdefault("defaults", {})["model"] = new_model
    save_config(cfg)
    return CommandResult(
        message=(
            f"\n[green]✓[/green] Model switched to: [cyan]{new_model}[/cyan]\n"
            "Restart 'trio agent' for the change to take effect.\n"
        )
    )


@command(
    "models",
    category=Category.MODEL,
    summary="List models available from the current provider",
    usage="/models",
    phase="P2",
)
async def cmd_models(ctx: "CommandContext", arg: str) -> CommandResult:
    """List models the running provider exposes.

    Uses ``provider.list_models()`` (async) when a provider is wired. triobot
    ships no models of its own, so if there is no provider or it reports none,
    this points the user at ``trio onboard`` / their provider instead.
    """
    provider = getattr(ctx, "provider", None)

    models: list[str] = []
    if provider is not None and hasattr(provider, "list_models"):
        try:
            result = await provider.list_models()
            if result:
                models = list(result)
        except Exception as e:  # never crash the REPL on a provider hiccup
            return CommandResult(
                message=(
                    f"\n[yellow]Could not list provider models:[/yellow] {e}\n"
                    "Check your provider config, then set one with /model <name>.\n"
                )
            )

    if not models:
        return CommandResult(
            message=(
                "\n[yellow]No models reported by the current provider.[/yellow]\n"
                "[dim]triobot is provider-agnostic and ships no models.[/dim]\n"
                "Configure a provider with [green]trio onboard[/green] "
                "(e.g. pull a model with [green]ollama pull llama3.1:8b[/green]), "
                "then set it with /model <name>.\n"
            )
        )

    listing = "\n".join(f"  [cyan]{m}[/cyan]" for m in models)
    return CommandResult(
        message=(
            f"\n[bold]Models[/bold] ([dim]current provider[/dim]):\n"
            f"{listing}\n"
            "Switch with: /model <name>\n"
        )
    )


@command(
    "connect",
    category=Category.MODEL,
    summary="Guide adding a provider and API key",
    usage="/connect",
    phase="P2",
)
async def cmd_connect(ctx: "CommandContext", arg: str) -> CommandResult:
    """Point users at the interactive provider-add flow.

    Honest stub: provider onboarding (prompting for name + API key) lives in the
    ``trio provider add`` CLI command, which cannot run inside the REPL prompt.
    """
    return CommandResult(
        message=(
            "\n[bold]Connect a provider[/bold]\n"
            "Adding a provider + API key is interactive, so run it from a terminal:\n\n"
            "  [green]trio provider add[/green]     add a new provider (name, base URL, API key)\n"
            "  [green]trio provider list[/green]    show configured providers\n\n"
            f"Available providers: {_PROVIDERS}\n"
            "Once added, switch with: /provider <name>\n"
        )
    )


@command(
    "effort",
    category=Category.MODEL,
    summary="Show or set reasoning effort",
    usage="/effort [minimal|low|medium|high]",
    phase="P2",
)
async def cmd_effort(ctx: "CommandContext", arg: str) -> CommandResult:
    """Show the current reasoning effort, or persist a new level.

    Stores the preference in ``config.agents.defaults.effort`` and mirrors it
    onto live agent state so the running loop can read it without a restart.
    """
    from triobot.core.config import load_config, save_config

    cfg = load_config()
    current = cfg.get("agents", {}).get("defaults", {}).get("effort", "medium")

    if not arg:
        return CommandResult(
            message=(
                f"\nReasoning effort: [cyan]{current}[/cyan]\n"
                f"Levels: {', '.join(_EFFORT_LEVELS)}\n"
                "Set with: /effort <level>\n"
            )
        )

    level = arg.lower().strip()
    if level not in _EFFORT_LEVELS:
        return CommandResult(
            message=(
                f"\n[yellow]Unknown effort level:[/yellow] {level}\n"
                f"Choose one of: {', '.join(_EFFORT_LEVELS)}\n"
            )
        )

    cfg.setdefault("agents", {}).setdefault("defaults", {})["effort"] = level
    save_config(cfg)

    # Mirror onto live agent state (best-effort; guard for None / missing attr).
    agent = getattr(ctx, "agent", None)
    if agent is not None:
        effort_state = getattr(agent, "_reasoning_effort", None)
        if isinstance(effort_state, dict):
            effort_state[ctx.session_key] = level

    return CommandResult(
        message=f"\n[green]✓[/green] Reasoning effort set to: [cyan]{level}[/cyan]\n"
    )


@command(
    "fast",
    category=Category.MODEL,
    summary="Show or toggle fast mode",
    usage="/fast [on|off]",
    phase="P2",
)
async def cmd_fast(ctx: "CommandContext", arg: str) -> CommandResult:
    """Show the current fast-mode state, or turn it on/off in config."""
    from triobot.core.config import load_config, save_config

    cfg = load_config()
    current = bool(cfg.get("agents", {}).get("defaults", {}).get("fast", False))

    if not arg:
        state = "on" if current else "off"
        return CommandResult(
            message=(
                f"\nFast mode: [cyan]{state}[/cyan]\n"
                "Toggle with: /fast on  |  /fast off\n"
            )
        )

    choice = arg.lower().strip()
    if choice in ("on", "true", "yes", "1", "enable", "enabled"):
        new_value = True
    elif choice in ("off", "false", "no", "0", "disable", "disabled"):
        new_value = False
    else:
        return CommandResult(
            message=f"\n[yellow]Usage:[/yellow] /fast [on|off]  (got: {choice})\n"
        )

    cfg.setdefault("agents", {}).setdefault("defaults", {})["fast"] = new_value
    save_config(cfg)
    state = "on" if new_value else "off"
    return CommandResult(
        message=f"\n[green]✓[/green] Fast mode turned [cyan]{state}[/cyan]\n"
    )


@command(
    "thinking",
    category=Category.MODEL,
    summary="Show or toggle visible reasoning",
    usage="/thinking [on|off]",
    aliases=("deepthink",),
    phase="P2",
)
async def cmd_thinking(ctx: "CommandContext", arg: str) -> CommandResult:
    """Toggle the visible reasoning stream on the live agent.

    Mutates ``ctx.agent._deep_thinking[ctx.session_key]`` — the same dict the
    agent loop reads (loop.py) — so the change takes effect on the next turn.
    Guards for a None agent (legacy/test channel construction).
    """
    agent = getattr(ctx, "agent", None)
    if agent is None or not hasattr(agent, "_deep_thinking"):
        return CommandResult(
            message="\n[yellow]Visible reasoning is unavailable[/yellow] (no live agent).\n"
        )

    key = ctx.session_key
    current = bool(agent._deep_thinking.get(key, False))

    choice = arg.lower().strip() if arg else ""
    if choice in ("on", "true", "yes", "1", "enable", "enabled"):
        new_value = True
    elif choice in ("off", "false", "no", "0", "disable", "disabled"):
        new_value = False
    elif not choice:
        new_value = not current  # bare /thinking flips it
    else:
        return CommandResult(
            message=f"\n[yellow]Usage:[/yellow] /thinking [on|off]  (got: {choice})\n"
        )

    agent._deep_thinking[key] = new_value
    state = "on" if new_value else "off"
    return CommandResult(
        message=f"\n[green]✓[/green] Visible reasoning turned [cyan]{state}[/cyan]\n"
    )
