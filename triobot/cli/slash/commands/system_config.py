"""System & Config commands (Category.SYSTEM).

Owns the system/config slash-commands:
    /help    /exit    /config (/settings)    /doctor    /permissions (/approvals)
    /theme    /update    /login    /logout

Where an in-process action is safe (config read/write, read-only diagnostics),
the command performs the real work. Long-running or blocking operations (update
reinstall, interactive OAuth) point the user at the equivalent `trio` CLI
subcommand rather than launching a blocking process inside the REPL.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from triobot.cli.slash.help import render_help
from triobot.cli.slash.model import Category, CommandResult
from triobot.cli.slash.registry import command

if TYPE_CHECKING:  # pragma: no cover - typing only
    from triobot.cli.slash.context import CommandContext

# Config keys that hold secrets — never echoed in plaintext by /config.
_SECRET_KEY_HINTS = (
    "token", "key", "secret", "password", "apikey", "auth", "sid",
)

# UI themes offered by /theme. No live theme engine exists yet, so /theme
# persists a preference under config["ui"]["theme"]; the console applies it on
# next launch once a theme system lands.
_THEMES = ("dark", "light", "system", "mono", "solarized")
_DEFAULT_THEME = "system"

# Approval modes surfaced by /permissions for a quick top-level toggle.
_APPROVAL_MODES = ("ask", "auto", "deny")


# ── /help ────────────────────────────────────────────────────────────────────

@command(
    "help",
    category=Category.SYSTEM,
    summary="Show this grouped command help",
    usage="/help [topic]",
    aliases=("?", "commands"),
)
async def cmd_help(ctx: "CommandContext", arg: str) -> CommandResult:
    """Auto-generated help. `/help <topic>` filters by category name."""
    return CommandResult(message=render_help(arg or None))


# ── /exit ────────────────────────────────────────────────────────────────────

@command(
    "exit",
    category=Category.SYSTEM,
    summary="Exit the chat",
    usage="/exit",
    aliases=("quit", "q"),
)
async def cmd_exit(ctx: "CommandContext", arg: str) -> CommandResult:
    """Request the REPL to quit."""
    return CommandResult(message="[dim]Goodbye![/dim]", exit_repl=True)


# ── /config ──────────────────────────────────────────────────────────────────

def _is_secretish(key: str) -> bool:
    """True if a config key name looks like it holds a secret."""
    low = key.lower()
    return any(hint in low for hint in _SECRET_KEY_HINTS)


def _redact(key: str, value: Any) -> str:
    """Render a config value, masking anything that looks like a secret."""
    if isinstance(value, (dict, list)):
        return f"[dim]<{type(value).__name__}, {len(value)} items>[/dim]"
    if _is_secretish(key) and value:
        return "[dim]***[/dim]"
    return str(value)


def _summarize_config(cfg: dict[str, Any]) -> str:
    """Build a concise, secret-safe summary of the current config."""
    defaults = cfg.get("agents", {}).get("defaults", {})
    tools_cfg = cfg.get("tools", {})
    channels = cfg.get("channels", {})
    enabled_channels = sorted(
        name for name, ch in channels.items()
        if isinstance(ch, dict) and ch.get("enabled")
    )
    ui = cfg.get("ui", {})

    lines = [
        "",
        "[bold]Current configuration[/bold] [dim](~/.trio/config.json)[/dim]",
        "",
        f"  provider          [cyan]{defaults.get('provider', 'ollama')}[/cyan]",
        f"  model             [cyan]{defaults.get('model') or '(not set)'}[/cyan]",
        f"  max_iterations    {defaults.get('max_iterations', 20)}",
        f"  memory_window     {defaults.get('memory_window', 20)}",
        f"  guardrails        {cfg.get('guardrails', {}).get('enabled', True)}",
        f"  restrictToWorkspace {tools_cfg.get('restrictToWorkspace', False)}",
        f"  approvals.enabled {cfg.get('approvals', {}).get('enabled', True)}",
        f"  ui.theme          [cyan]{ui.get('theme', _DEFAULT_THEME)}[/cyan]",
        f"  channels enabled  {', '.join(enabled_channels) or '[dim]none[/dim]'}",
        "",
        "[dim]Set a value:  /config <dotted.key> <value>"
        "   e.g. /config agents.defaults.memory_window 40[/dim]",
        "[dim]Top-level sections: "
        + ", ".join(sorted(cfg.keys()))
        + "[/dim]",
        "",
    ]
    return "\n".join(lines)


def _coerce_value(raw: str) -> Any:
    """Coerce a CLI string into bool / int / float where unambiguous."""
    low = raw.strip().lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    if low in ("null", "none"):
        return None
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw


def _set_dotted(cfg: dict[str, Any], dotted: str, value: Any) -> None:
    """Set cfg[a][b][c] = value for a dotted 'a.b.c' key, creating dicts."""
    parts = dotted.split(".")
    node = cfg
    for part in parts[:-1]:
        existing = node.get(part)
        if not isinstance(existing, dict):
            existing = {}
            node[part] = existing
        node = existing
    node[parts[-1]] = value


@command(
    "config",
    category=Category.SYSTEM,
    summary="Show config summary, or set a dotted key: /config a.b.c value",
    usage="/config [key] [value]",
    aliases=("settings",),
)
async def cmd_config(ctx: "CommandContext", arg: str) -> CommandResult:
    """Show the config summary, or persist a top-level/dotted key.

    `/config` with no argument prints a secret-safe summary.
    `/config <dotted.key> <value>` coerces the value (bool/int/float) and saves.
    """
    from triobot.core.config import load_config, save_config

    cfg = load_config()

    if not arg:
        return CommandResult(message=_summarize_config(cfg))

    parts = arg.split(maxsplit=1)
    key = parts[0].strip()
    if len(parts) < 2 or not parts[1].strip():
        # Show a single key's current value (secret-safe).
        node: Any = cfg
        for seg in key.split("."):
            if isinstance(node, dict) and seg in node:
                node = node[seg]
            else:
                return CommandResult(
                    message=(
                        f"\n[yellow]No such config key:[/yellow] {key}\n"
                        "Usage: /config <dotted.key> <value>\n"
                    )
                )
        leaf = key.split(".")[-1]
        return CommandResult(
            message=f"\n{key} = {_redact(leaf, node)}\n"
        )

    value = _coerce_value(parts[1].strip())
    _set_dotted(cfg, key, value)
    save_config(cfg)
    leaf = key.split(".")[-1]
    shown = "[dim]***[/dim]" if _is_secretish(leaf) and value else value
    return CommandResult(
        message=(
            f"\n[green]OK[/green] Set [cyan]{key}[/cyan] = {shown}\n"
            "[dim]Some changes take effect on the next 'trio agent' launch.[/dim]\n"
        )
    )


# ── /doctor ──────────────────────────────────────────────────────────────────

@command(
    "doctor",
    category=Category.SYSTEM,
    summary="Run environment diagnostics (read-only)",
    usage="/doctor",
)
async def cmd_doctor(ctx: "CommandContext", arg: str) -> CommandResult:
    """Run the same diagnostics as `trio doctor` (never auto-fixes).

    `run_doctor(fix=False)` is read-only and prints via its own Console, so it
    is safe to call in-process. Auto-repair (`--fix`) is intentionally not run
    from the REPL; the message points at the CLI for that.
    """
    try:
        from triobot.cli.doctor_cmd import run_doctor

        await run_doctor(fix=False)
        return CommandResult(
            message="[dim]To auto-repair fixable issues, run: trio doctor --fix[/dim]"
        )
    except Exception as exc:  # never crash the REPL on a diagnostic error
        return CommandResult(
            message=(
                f"[yellow]Could not run diagnostics in-process:[/yellow] {exc}\n"
                "[dim]Run in a separate terminal: trio doctor[/dim]"
            )
        )


# ── /permissions ─────────────────────────────────────────────────────────────

def _summarize_permissions(cfg: dict[str, Any]) -> str:
    """Build a summary of the tool/guardrail approval settings."""
    approvals = cfg.get("approvals", {})
    tools_cfg = cfg.get("tools", {})
    guardrails = cfg.get("guardrails", {})
    auto = approvals.get("auto_approve_types", []) or []
    deny = approvals.get("deny_types", []) or []
    builtin = tools_cfg.get("builtin", []) or []

    lines = [
        "",
        "[bold]Tool & guardrail permissions[/bold]",
        "",
        f"  approvals.enabled     {approvals.get('enabled', True)} "
        "[dim](confirm dangerous tools before running)[/dim]",
        f"  guardrails.enabled    {guardrails.get('enabled', True)} "
        "[dim](input/output filtering)[/dim]",
        f"  restrictToWorkspace   {tools_cfg.get('restrictToWorkspace', False)} "
        "[dim](limit file/shell to the workspace)[/dim]",
        "",
        f"  auto-approve tools    {', '.join(auto) or '[dim]none[/dim]'}",
        f"  denied tools          {', '.join(deny) or '[dim]none[/dim]'}",
        f"  enabled builtin tools {', '.join(builtin) or '[dim]none[/dim]'}",
        "",
        "[bold]Edit[/bold]",
        "  /permissions mode ask|auto|deny   [dim]top-level approval behavior[/dim]",
        "  /permissions allow <tool>         [dim]auto-approve a tool[/dim]",
        "  /permissions deny <tool>          [dim]always block a tool[/dim]",
        "  /permissions reset <tool>         [dim]clear allow/deny for a tool[/dim]",
        "  /permissions guardrails on|off    [dim]toggle input/output filtering[/dim]",
        "  /permissions sandbox on|off       [dim]toggle workspace restriction[/dim]",
        "",
    ]
    return "\n".join(lines)


def _set_permission_mode(cfg: dict[str, Any], mode: str) -> str:
    """Apply a top-level approval mode; returns a status message."""
    approvals = cfg.setdefault("approvals", {})
    if mode == "auto":
        approvals["enabled"] = False
        return "Approval mode: [cyan]auto[/cyan] (dangerous tools run without asking)."
    if mode == "deny":
        approvals["enabled"] = True
        return (
            "Approval mode: [cyan]deny[/cyan] — set specific tools with "
            "/permissions deny <tool>."
        )
    approvals["enabled"] = True
    return "Approval mode: [cyan]ask[/cyan] (confirm dangerous tools before running)."


def _toggle_tool_list(cfg: dict[str, Any], list_key: str, tool: str, add: bool) -> None:
    """Add/remove a tool from approvals[list_key], keeping the list unique."""
    approvals = cfg.setdefault("approvals", {})
    items = list(approvals.get(list_key, []) or [])
    if add and tool not in items:
        items.append(tool)
    elif not add and tool in items:
        items = [t for t in items if t != tool]
    approvals[list_key] = items


def _parse_on_off(token: str) -> bool | None:
    low = token.strip().lower()
    if low in ("on", "true", "yes", "enable", "enabled"):
        return True
    if low in ("off", "false", "no", "disable", "disabled"):
        return False
    return None


@command(
    "permissions",
    category=Category.SYSTEM,
    summary="Show or edit tool/guardrail approval settings",
    usage="/permissions [mode|allow|deny|reset|guardrails|sandbox] [value]",
    aliases=("approvals",),
)
async def cmd_permissions(ctx: "CommandContext", arg: str) -> CommandResult:
    """Show the approval/guardrail policy, or edit it and persist."""
    from triobot.core.config import load_config, save_config

    cfg = load_config()

    if not arg:
        return CommandResult(message=_summarize_permissions(cfg))

    parts = arg.split(maxsplit=1)
    sub = parts[0].strip().lower()
    rest = parts[1].strip() if len(parts) > 1 else ""

    if sub == "mode":
        if rest.lower() not in _APPROVAL_MODES:
            return CommandResult(
                message=f"\nUsage: /permissions mode {'|'.join(_APPROVAL_MODES)}\n"
            )
        status = _set_permission_mode(cfg, rest.lower())
        save_config(cfg)
        return CommandResult(message=f"\n[green]OK[/green] {status}\n")

    if sub in ("allow", "deny", "reset"):
        if not rest:
            return CommandResult(message=f"\nUsage: /permissions {sub} <tool>\n")
        tool = rest.split()[0]
        if sub == "allow":
            _toggle_tool_list(cfg, "auto_approve_types", tool, add=True)
            _toggle_tool_list(cfg, "deny_types", tool, add=False)
            msg = f"Tool [cyan]{tool}[/cyan] will now auto-approve."
        elif sub == "deny":
            _toggle_tool_list(cfg, "deny_types", tool, add=True)
            _toggle_tool_list(cfg, "auto_approve_types", tool, add=False)
            msg = f"Tool [cyan]{tool}[/cyan] is now always blocked."
        else:  # reset
            _toggle_tool_list(cfg, "auto_approve_types", tool, add=False)
            _toggle_tool_list(cfg, "deny_types", tool, add=False)
            msg = f"Tool [cyan]{tool}[/cyan] reset to the default (ask)."
        save_config(cfg)
        return CommandResult(message=f"\n[green]OK[/green] {msg}\n")

    if sub == "guardrails":
        flag = _parse_on_off(rest)
        if flag is None:
            return CommandResult(message="\nUsage: /permissions guardrails on|off\n")
        cfg.setdefault("guardrails", {})["enabled"] = flag
        save_config(cfg)
        state = "enabled" if flag else "disabled"
        return CommandResult(
            message=f"\n[green]OK[/green] Guardrails [cyan]{state}[/cyan].\n"
        )

    if sub == "sandbox":
        flag = _parse_on_off(rest)
        if flag is None:
            return CommandResult(message="\nUsage: /permissions sandbox on|off\n")
        cfg.setdefault("tools", {})["restrictToWorkspace"] = flag
        save_config(cfg)
        state = "on" if flag else "off"
        return CommandResult(
            message=(
                f"\n[green]OK[/green] Workspace restriction [cyan]{state}[/cyan].\n"
                "[dim]Takes effect on the next 'trio agent' launch.[/dim]\n"
            )
        )

    return CommandResult(message=_summarize_permissions(cfg))


# ── /theme ───────────────────────────────────────────────────────────────────

@command(
    "theme",
    category=Category.SYSTEM,
    summary="Show, list, or set the UI theme preference",
    usage="/theme [name]",
    aliases=("themes",),
)
async def cmd_theme(ctx: "CommandContext", arg: str) -> CommandResult:
    """Show the current theme, list options, or persist a new one.

    No live theme engine exists yet, so the choice is stored under
    config["ui"]["theme"] and applied on the next launch.
    """
    from triobot.core.config import load_config, save_config

    cfg = load_config()
    current = cfg.get("ui", {}).get("theme", _DEFAULT_THEME)

    if not arg:
        options = ", ".join(
            f"[cyan]{t}[/cyan]" if t == current else t for t in _THEMES
        )
        return CommandResult(
            message=(
                f"\nCurrent theme: [cyan]{current}[/cyan]\n"
                f"Available: {options}\n"
                "Set with: /theme <name>\n"
            )
        )

    choice = arg.strip().lower()
    if choice not in _THEMES:
        return CommandResult(
            message=(
                f"\n[yellow]Unknown theme:[/yellow] {choice}\n"
                f"Available: {', '.join(_THEMES)}\n"
            )
        )

    cfg.setdefault("ui", {})["theme"] = choice
    save_config(cfg)
    return CommandResult(
        message=(
            f"\n[green]OK[/green] Theme set to [cyan]{choice}[/cyan].\n"
            "[dim]Applied on the next 'trio agent' launch.[/dim]\n"
        )
    )


# ── /update ──────────────────────────────────────────────────────────────────

@command(
    "update",
    category=Category.SYSTEM,
    summary="How to update trio to the latest version",
    usage="/update",
)
async def cmd_update(ctx: "CommandContext", arg: str) -> CommandResult:
    """Point at `trio update` rather than reinstalling inside the REPL.

    `run_update` shells out to git/pip and reinstalls the package — a blocking,
    long-running operation that must not run inside the interactive loop.
    """
    channel = arg.strip() or "stable"
    return CommandResult(
        message=(
            "\n[bold]Update trio[/bold]\n"
            "Updates reinstall the package, so run this from a separate terminal:\n"
            f"  [cyan]trio update[/cyan]"
            + (f" [cyan]--channel {channel}[/cyan]" if channel != "stable" else "")
            + "\n[dim]Restart 'trio agent' afterward to load the new version.[/dim]\n"
        )
    )


# ── /login ───────────────────────────────────────────────────────────────────

@command(
    "login",
    category=Category.SYSTEM,
    summary="Log in to a provider (interactive)",
    usage="/login",
)
async def cmd_login(ctx: "CommandContext", arg: str) -> CommandResult:
    """Point at the interactive `trio provider` flow.

    Provider login is interactive (prompts / OAuth) and does not belong inside
    the REPL's async loop. `trio provider login` is the single-sourced entry;
    it currently reports OAuth login as not yet implemented, so add API-key
    providers with `trio provider add`.
    """
    return CommandResult(
        message=(
            "\n[bold]Provider login[/bold]\n"
            "Run the interactive flow from a separate terminal:\n"
            "  [cyan]trio provider login[/cyan]   [dim](OAuth — not yet implemented)[/dim]\n"
            "  [cyan]trio provider add[/cyan]     [dim](add an API-key provider now)[/dim]\n"
        )
    )


# ── /logout ──────────────────────────────────────────────────────────────────

@command(
    "logout",
    category=Category.SYSTEM,
    summary="Clear a stored provider credential",
    usage="/logout [provider]",
)
async def cmd_logout(ctx: "CommandContext", arg: str) -> CommandResult:
    """Clear a stored API key/token for a provider from config.

    No dedicated logout runner exists in the CLI, so this performs the
    equivalent config edit directly: it blanks the stored secret fields for the
    named provider (default: the active one) and saves.
    """
    from triobot.core.config import load_config, save_config

    cfg = load_config()
    provider = (
        arg.strip().lower()
        or cfg.get("agents", {}).get("defaults", {}).get("provider", "ollama")
    )

    providers = cfg.get("providers", {})
    pconf = providers.get(provider)
    if not isinstance(pconf, dict):
        return CommandResult(
            message=(
                f"\n[yellow]No stored config for provider:[/yellow] {provider}\n"
                f"Configured: {', '.join(sorted(providers.keys())) or 'none'}\n"
            )
        )

    cleared = []
    for field_name in list(pconf.keys()):
        if _is_secretish(field_name) and pconf.get(field_name):
            pconf[field_name] = ""
            cleared.append(field_name)

    if not cleared:
        return CommandResult(
            message=(
                f"\n[dim]No stored credentials to clear for "
                f"[cyan]{provider}[/cyan].[/dim]\n"
            )
        )

    save_config(cfg)
    return CommandResult(
        message=(
            f"\n[green]OK[/green] Cleared credentials for "
            f"[cyan]{provider}[/cyan]: {', '.join(cleared)}\n"
            "[dim]Restart 'trio agent' for the change to take full effect.[/dim]\n"
        )
    )
