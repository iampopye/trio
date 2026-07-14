"""Agents, Tools, MCP & Skills commands (Category.AGENTS).

Provides the interactive REPL surface for inspecting and driving triobot's
agent/tool subsystems:

    /skill               list installed skills / install one (Phase 0 migration)
    /tools               list registered agent tools + descriptions
    /agents (/agent)     list sub-agents; /agents <name> shows detail
    /mcp                 list configured MCP servers and their tools
    /plugins (/plugin)   list installed plugins
    /fork <directive>    spawn a sub-agent for a one-off directive

Every handler receives the live CommandContext and touches only refs already
present on it. Where the underlying API is not available (no sub-agent registry,
no MCP configured, no delegate tool), the command degrades to an honest message
instead of faking success.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

from typing import TYPE_CHECKING

from triobot.cli.slash.model import Category, CommandResult
from triobot.cli.slash.registry import command

if TYPE_CHECKING:  # pragma: no cover - typing only
    from triobot.cli.slash.context import CommandContext

_MAX_LISTED_SKILLS = 50
_MAX_LISTED_TOOLS = 100
_MAX_LISTED_MCP_TOOLS = 60
_SUMMARY_TRUNCATE = 80


def _first_line(text: str, limit: int = _SUMMARY_TRUNCATE) -> str:
    """Collapse a (possibly multi-line) description to a single trimmed line."""
    if not text:
        return ""
    line = text.strip().splitlines()[0].strip()
    if len(line) > limit:
        line = line[: limit - 1].rstrip() + "…"
    return line


def _schema_descriptions(ctx: "CommandContext") -> dict[str, str]:
    """Map tool name -> first-line description from ToolRegistry.get_schemas().

    Schema shape (see ToolRegistry.to_schema): {"type":"function",
    "function":{"name":..., "description":..., "parameters":...}}.
    Falls back to an empty dict on any unexpected shape.
    """
    out: dict[str, str] = {}
    try:
        for schema in ctx.tools.get_schemas():
            fn = schema.get("function", {}) if isinstance(schema, dict) else {}
            name = fn.get("name")
            if name:
                out[name] = _first_line(fn.get("description", ""))
    except Exception:  # pragma: no cover - defensive; never crash the REPL
        return {}
    return out


@command(
    "skill",
    category=Category.AGENTS,
    summary="List installed skills or install one from TrioHub",
    usage="/skill list | install <name>",
    aliases=("skills",),
)
async def cmd_skill(ctx: "CommandContext", arg: str) -> CommandResult:
    """List or install skills (migrated from _slash_skill)."""
    if not arg or arg == "list":
        from triobot.core.config import get_skills_dir

        skills_dir = get_skills_dir()
        files = list(skills_dir.glob("*.md")) if skills_dir.is_dir() else []
        if not files:
            return CommandResult(
                message=(
                    "\nNo skills installed yet.\n"
                    "Browse: [cyan]trio hub trending[/cyan]\n"
                    "Install: [cyan]/skill install <name>[/cyan]\n"
                )
            )
        lines = [f"\nInstalled skills ({len(files)}):"]
        for f in sorted(files)[:_MAX_LISTED_SKILLS]:
            lines.append(f"  • {f.stem}")
        if len(files) > _MAX_LISTED_SKILLS:
            lines.append(f"  ... and {len(files) - _MAX_LISTED_SKILLS} more")
        return CommandResult(message="\n".join(lines) + "\n")

    if arg.startswith("install "):
        skill_name = arg[len("install "):].strip()
        return CommandResult(
            message=(
                f"\nTo install '{skill_name}', run in a separate terminal:\n"
                f"  [cyan]trio skill install {skill_name}[/cyan]\n"
            )
        )

    return CommandResult(message="\nUsage: /skill list | /skill install <name>\n")


@command(
    "tools",
    category=Category.AGENTS,
    summary="List registered agent tools and their descriptions",
    usage="/tools",
    phase="P3",
)
async def cmd_tools(ctx: "CommandContext", arg: str) -> CommandResult:
    """List every tool registered on the live ToolRegistry.

    Real behavior: reads ctx.tools.list_tools() for names and pairs each with a
    one-line description from ctx.tools.get_schemas().
    """
    tools = getattr(ctx, "tools", None)
    if tools is None:
        return CommandResult(
            message="\n[yellow]Tool registry is not available in this session.[/yellow]\n"
        )

    names = sorted(tools.list_tools())
    if not names:
        return CommandResult(
            message=(
                "\nNo tools registered.\n"
                "Enable built-in tools under [cyan]tools.builtin[/cyan] in your config,\n"
                "then restart 'trio agent'.\n"
            )
        )

    descriptions = _schema_descriptions(ctx)
    lines = [f"\nRegistered tools ({len(names)}):"]
    for name in names[:_MAX_LISTED_TOOLS]:
        desc = descriptions.get(name, "")
        if desc:
            lines.append(f"  • [cyan]{name}[/cyan] — {desc}")
        else:
            lines.append(f"  • [cyan]{name}[/cyan]")
    if len(names) > _MAX_LISTED_TOOLS:
        lines.append(f"  ... and {len(names) - _MAX_LISTED_TOOLS} more")
    return CommandResult(message="\n".join(lines) + "\n")


def _agent_detail(cfg) -> str:
    """Render a single sub-agent config as a detail block."""
    name = getattr(cfg, "name", "?")
    role = getattr(cfg, "role", "") or ""
    model = getattr(cfg, "model", None)
    provider = getattr(cfg, "provider", None)
    agent_tools = getattr(cfg, "tools", None) or []
    max_iterations = getattr(cfg, "max_iterations", None)

    lines = [f"\n[bold cyan]{name}[/bold cyan]"]
    if provider or model:
        route = f"{provider or 'default'}"
        if model:
            route += f" · {model}"
        lines.append(f"  routing:    {route}")
    else:
        lines.append("  routing:    provider default")
    if agent_tools:
        lines.append(f"  tools:      {', '.join(agent_tools)}")
    else:
        lines.append("  tools:      (inherits parent tools)")
    if max_iterations is not None:
        lines.append(f"  max_iters:  {max_iterations}")
    if role:
        lines.append(f"  role:       {_first_line(role, limit=200)}")
    return "\n".join(lines) + "\n"


@command(
    "agents",
    category=Category.AGENTS,
    summary="List available sub-agents; /agents <name> shows detail",
    usage="/agents [name]",
    aliases=("agent",),
    phase="P3",
)
async def cmd_agents(ctx: "CommandContext", arg: str) -> CommandResult:
    """List sub-agents from ctx.agent.subagent_registry, or show one in detail.

    Real behavior when the agent exposes `subagent_registry` (SubAgentRegistry).
    Degrades to an honest stub if the agent or the registry is absent.
    """
    agent = getattr(ctx, "agent", None)
    registry = getattr(agent, "subagent_registry", None) if agent is not None else None
    if registry is None:
        return CommandResult(
            message=(
                "\n[yellow]Sub-agent registry is not available in this session.[/yellow]\n"
                "Sub-agents are configured on the running agent loop; start with\n"
                "[cyan]trio agent[/cyan] and enable the [cyan]delegate[/cyan] tool "
                "under tools.builtin.\n"
            )
        )

    try:
        configs = list(registry.list_agents())
    except Exception as e:  # pragma: no cover - defensive
        return CommandResult(message=f"\n[red]Could not read sub-agents:[/red] {e}\n")

    # Detail view: /agents <name>
    target = arg.strip()
    if target:
        cfg = None
        getter = getattr(registry, "get", None)
        if callable(getter):
            cfg = getter(target)
        if cfg is None:
            cfg = next(
                (c for c in configs if getattr(c, "name", None) == target),
                None,
            )
        if cfg is None:
            available = ", ".join(sorted(getattr(c, "name", "?") for c in configs)) or "none"
            return CommandResult(
                message=(
                    f"\n[yellow]Unknown sub-agent:[/yellow] {target}\n"
                    f"Available: {available}\n"
                )
            )
        return CommandResult(message=_agent_detail(cfg))

    # List view
    if not configs:
        return CommandResult(
            message="\nNo sub-agents registered.\n"
        )
    lines = [f"\nAvailable sub-agents ({len(configs)}):"]
    for cfg in sorted(configs, key=lambda c: getattr(c, "name", "")):
        name = getattr(cfg, "name", "?")
        role = _first_line(getattr(cfg, "role", "") or "")
        if role:
            lines.append(f"  • [cyan]{name}[/cyan] — {role}")
        else:
            lines.append(f"  • [cyan]{name}[/cyan]")
    lines.append("\nDetail: [cyan]/agents <name>[/cyan]")
    return CommandResult(message="\n".join(lines) + "\n")


@command(
    "mcp",
    category=Category.AGENTS,
    summary="List configured MCP servers and their tools",
    usage="/mcp",
    phase="P3",
)
async def cmd_mcp(ctx: "CommandContext", arg: str) -> CommandResult:
    """List MCP servers via ctx.mcp_manager, plus their discovered tools.

    Real behavior when an MCPManager with started servers is present. When no
    MCP is configured (mcp_manager is None), print an honest message pointing to
    the config location rather than faking a server list.
    """
    manager = getattr(ctx, "mcp_manager", None)
    if manager is None:
        return CommandResult(
            message=(
                "\nNo MCP servers configured.\n"
                "Add servers under the [cyan]mcp[/cyan] key of your config "
                "([cyan]~/.trio/config.json[/cyan]),\n"
                "then restart 'trio agent'.\n"
            )
        )

    servers = getattr(manager, "_servers", None)
    if not servers:
        return CommandResult(
            message=(
                "\nMCP manager is active but no servers are connected.\n"
                "Check the [cyan]mcp[/cyan] section of [cyan]~/.trio/config.json[/cyan] "
                "and restart 'trio agent'.\n"
            )
        )

    # MCP tools are registered into the main ToolRegistry with a "<server>_" prefix.
    tool_names: list[str] = []
    tools = getattr(ctx, "tools", None)
    if tools is not None:
        try:
            tool_names = list(tools.list_tools())
        except Exception:  # pragma: no cover - defensive
            tool_names = []

    lines = [f"\nMCP servers ({len(servers)}):"]
    for server_name in sorted(servers):
        server = servers[server_name]
        transport = getattr(server, "transport", "stdio")
        lines.append(f"  • [cyan]{server_name}[/cyan] [dim]({transport})[/dim]")
        prefix = f"{server_name}_"
        matched = sorted(t for t in tool_names if t.startswith(prefix))
        for tool_name in matched[:_MAX_LISTED_MCP_TOOLS]:
            lines.append(f"      - {tool_name}")
        if len(matched) > _MAX_LISTED_MCP_TOOLS:
            lines.append(f"      ... and {len(matched) - _MAX_LISTED_MCP_TOOLS} more")
        if not matched:
            lines.append("      [dim](no tools discovered)[/dim]")
    return CommandResult(message="\n".join(lines) + "\n")


@command(
    "plugins",
    category=Category.AGENTS,
    summary="List installed plugins",
    usage="/plugins",
    aliases=("plugin",),
    phase="P3",
)
async def cmd_plugins(ctx: "CommandContext", arg: str) -> CommandResult:
    """List installed plugins via the PluginManager.

    Real behavior: wraps the same PluginManager.list_plugins() that backs
    `trio plugin list`, so the REPL and CLI stay single-sourced.
    """
    try:
        from triobot.plugins.manager import PluginManager
    except Exception as e:  # pragma: no cover - import guard
        return CommandResult(
            message=(
                f"\n[yellow]Plugin subsystem unavailable:[/yellow] {e}\n"
                "Manage plugins from the CLI: [cyan]trio plugin list[/cyan]\n"
            )
        )

    try:
        plugins = PluginManager().list_plugins()
    except Exception as e:
        return CommandResult(
            message=(
                f"\n[red]Could not list plugins:[/red] {e}\n"
                "Try the CLI: [cyan]trio plugin list[/cyan]\n"
            )
        )

    if not plugins:
        return CommandResult(
            message=(
                "\nNo plugins installed.\n"
                "Install one: [cyan]trio plugin install <path>[/cyan]\n"
            )
        )

    lines = [f"\nInstalled plugins ({len(plugins)}):"]
    for p in sorted(plugins, key=lambda x: getattr(x, "name", "")):
        name = getattr(p, "name", "?")
        version = getattr(p, "version", "")
        enabled = getattr(p, "enabled", True)
        n_tools = len(getattr(p, "tools", []) or [])
        n_skills = len(getattr(p, "skills", []) or [])
        status = "[green]enabled[/green]" if enabled else "[red]disabled[/red]"
        ver = f" v{version}" if version else ""
        lines.append(
            f"  • [cyan]{name}[/cyan]{ver} — {status} "
            f"[dim]({n_tools} tools, {n_skills} skills)[/dim]"
        )
    lines.append("\nManage: [cyan]trio plugin <install|enable|disable|uninstall>[/cyan]")
    return CommandResult(message="\n".join(lines) + "\n")


@command(
    "fork",
    category=Category.AGENTS,
    summary="Spawn a sub-agent to handle a one-off directive",
    usage="/fork [agent] <directive>",
    phase="P3",
)
async def cmd_fork(ctx: "CommandContext", arg: str) -> CommandResult:
    """Delegate a directive to a sub-agent via the `delegate` tool.

    Real behavior when the `delegate` tool is registered: resolves a target
    sub-agent (an explicit first token that names a known agent, otherwise a
    sensible default) and runs it through ctx.tools.execute("delegate", ...).
    When the delegate tool is absent, returns an honest stub pointing to how to
    enable it rather than pretending to fork.
    """
    directive = arg.strip()
    if not directive:
        return CommandResult(
            message=(
                "\n[yellow]Usage:[/yellow] /fork [agent] <directive>\n"
                "Example: [cyan]/fork researcher find the latest asyncio docs[/cyan]\n"
            )
        )

    tools = getattr(ctx, "tools", None)
    tool_names: list[str] = []
    if tools is not None:
        try:
            tool_names = list(tools.list_tools())
        except Exception:  # pragma: no cover - defensive
            tool_names = []

    if "delegate" not in tool_names:
        return CommandResult(
            message=(
                "\n[yellow]/fork is not available yet in this session.[/yellow]\n"
                "It requires the [cyan]delegate[/cyan] sub-agent tool. Enable it by\n"
                "adding [cyan]\"delegate\"[/cyan] to [cyan]tools.builtin[/cyan] in your "
                "config, then restart 'trio agent'.\n"
            )
        )

    # Resolve available sub-agent names to allow an optional leading agent token.
    agent = getattr(ctx, "agent", None)
    registry = getattr(agent, "subagent_registry", None) if agent is not None else None
    known: list[str] = []
    if registry is not None:
        names_fn = getattr(registry, "names", None)
        try:
            if callable(names_fn):
                known = list(names_fn())
            else:
                known = [getattr(c, "name", "") for c in registry.list_agents()]
        except Exception:  # pragma: no cover - defensive
            known = []

    parts = directive.split(maxsplit=1)
    agent_name = ""
    task = directive
    if len(parts) == 2 and parts[0] in known:
        agent_name, task = parts[0], parts[1]
    elif len(parts) == 1 and parts[0] in known:
        # A bare known agent name with no task — ask for the directive.
        return CommandResult(
            message=(
                f"\n[yellow]Provide a directive for '{parts[0]}':[/yellow] "
                f"/fork {parts[0]} <directive>\n"
            )
        )

    if not agent_name:
        # Pick a default: prefer a general-purpose agent, else the first known.
        for preferred in ("researcher", "general", "coder"):
            if preferred in known:
                agent_name = preferred
                break
        if not agent_name and known:
            agent_name = known[0]

    if not agent_name:
        return CommandResult(
            message=(
                "\n[yellow]No sub-agents are registered to fork.[/yellow]\n"
                "Register sub-agents on the agent loop before using /fork.\n"
            )
        )

    try:
        result = await ctx.tools.execute(
            "delegate", {"agent_name": agent_name, "task": task}
        )
    except Exception as e:  # pragma: no cover - defensive; execute() already guards
        return CommandResult(message=f"\n[red]/fork failed:[/red] {e}\n")

    output = getattr(result, "output", str(result))
    if getattr(result, "success", True):
        header = f"[green]✓[/green] Forked sub-agent [cyan]{agent_name}[/cyan]:"
    else:
        header = f"[red]✗[/red] Sub-agent [cyan]{agent_name}[/cyan] failed:"
    return CommandResult(message=f"\n{header}\n{output}\n")
