"""trio help — show all commands grouped by category, with examples."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

console = Console()


# ── Command catalogue ──────────────────────────────────────────────────────
# Single source of truth for `trio help` and the web UI /api/help endpoint.

COMMAND_CATALOG = {
    "Setup & Diagnostics": [
        ("trio onboard", "Interactive setup wizard (auto-detects Ollama, picks model, configures channels)"),
        ("trio doctor", "Diagnose system issues (deps, paths, providers)"),
        ("trio doctor --fix", "Auto-repair common issues"),
        ("trio status", "System overview: providers, channels, daemon health"),
        ("trio help", "Show this help"),
        ("trio help <command>", "Detailed help for a specific command"),
        ("trio --version", "Show installed version"),
    ],
    "Chat & Agent": [
        ("trio agent", "Interactive chat in your terminal"),
        ("trio agent -m \"...\"", "Send a single message and exit"),
        ("trio agent --no-markdown", "Plain text output (for piping)"),
        ("trio agent --logs", "Show runtime logs alongside chat"),
        ("trio serve", "Start the browser UI on http://localhost:28337"),
        ("trio serve --port 8080", "Custom port"),
    ],
    "Models & Providers": [
        ("trio provider list", "Show configured providers and active model"),
        ("trio provider add", "Add a new LLM provider interactively"),
        ("trio provider set --model trio-max", "Set default model"),
        ("trio provider set --provider openai --model gpt-4o", "Switch provider + model"),
        ("trio provider login", "OAuth login (e.g. GitHub Models)"),
    ],
    "Built-in trio model tiers": [
        ("trio-nano  (~1M params, 600 MB)", "CPU, 4 GB RAM — embedded, IoT, testing"),
        ("trio-small (~125M params, 1.2 GB)", "CPU/GPU, 8 GB RAM — lightweight chat"),
        ("trio-medium (~350M params, 2.5 GB)", "GPU/Apple Silicon — personal assistant"),
        ("trio-high (~750M params, 5 GB)", "RTX 3060+, M2+ — production workloads"),
        ("trio-max (~3B params, 5.6 GB)", "RTX 4070+, M3+ — enterprise tasks"),
        ("trio-pro (~30B MoE, 18 GB)", "RTX 4090, A100 — research, advanced agents"),
    ],
    "Skills (3,876 community-curated)": [
        ("trio skill list", "Show installed skills"),
        ("trio skill install <name>", "Install a skill from TrioHub"),
        ("trio skill remove <name>", "Remove an installed skill"),
        ("trio skill search \"<query>\"", "Search the local skill index"),
        ("trio hub search \"<query>\"", "Search 3,876 skills in the registry"),
        ("trio hub trending", "Show trending skills"),
    ],
    "Plugins": [
        ("trio plugin list", "Show installed plugins"),
        ("trio plugin install <path|url>", "Install a plugin"),
        ("trio plugin uninstall <name>", "Remove a plugin"),
        ("trio plugin enable <name>", "Enable a plugin"),
        ("trio plugin disable <name>", "Disable a plugin"),
    ],
    "Channels & Daemon": [
        ("trio gateway", "Start all enabled channels (foreground)"),
        ("trio daemon install", "Install as system service (auto-start on boot)"),
        ("trio daemon start", "Start the daemon"),
        ("trio daemon stop", "Stop the daemon"),
        ("trio daemon restart", "Restart the daemon"),
        ("trio daemon status", "PID, uptime, channel health"),
        ("trio daemon logs", "Tail recent daemon logs"),
        ("trio daemon uninstall", "Remove the system service"),
    ],
    "Training": [
        ("trio train --setup", "Download pre-trained GGUF models"),
        ("trio train", "Train from scratch (resume with Ctrl+C)"),
        ("trio train --reset", "Restart training from scratch"),
    ],
    "Security & Pairing": [
        ("trio pairing list", "Show pairing status across channels"),
        ("trio pairing pending", "Show pending DM pairing requests"),
        ("trio pairing approve <chan> <code>", "Approve a pairing request"),
        ("trio pairing revoke <chan> <user>", "Revoke a user's access"),
    ],
    "Maintenance": [
        ("trio update", "Update to the latest version"),
        ("trio update --channel beta", "Switch to beta channel"),
        ("trio heartbeat status", "Heartbeat monitor status"),
        ("trio heartbeat log", "Recent heartbeat log"),
    ],
}


# ── Detailed help for individual commands ─────────────────────────────────

DETAILED_HELP = {
    "agent": """
[bold cyan]trio agent[/bold cyan] — Interactive chat with your AI agent.

[bold]Usage:[/bold]
  trio agent
  trio agent -m "summarize this PR"
  trio agent --no-markdown
  trio agent --logs

[bold]In-chat slash commands:[/bold]
  /help              Show available slash commands
  /provider          Switch LLM provider with picker
  /model <name>      Change model (e.g. /model trio-max)
  /skill list        List installed skills
  /skill install X   Install a skill from TrioHub
  /clear             Clear chat history
  /save <name>       Save current session
  /load <name>       Load a saved session
  /exit              Exit the chat

[bold]Tips:[/bold]
  - Use [cyan]Ctrl+C[/cyan] to interrupt streaming output
  - Sessions are auto-saved to ~/.trio/sessions/
  - Memory persists across sessions automatically
""",
    "provider": """
[bold cyan]trio provider[/bold cyan] — Manage LLM providers.

[bold]Sub-commands:[/bold]
  trio provider list                          Show configured providers
  trio provider add                            Add a new provider (interactive)
  trio provider set --model trio-max           Set default model
  trio provider set --provider openai --model gpt-4o
  trio provider login                          OAuth login (GitHub Models, etc.)

[bold]Supported providers:[/bold]
  - [green]Local trio-* models[/green] (free, runs on your machine)
  - [green]Ollama[/green] (free, local, requires Ollama running)
  - [green]Groq[/green] (free tier, fast)
  - [green]Google Gemini[/green] (free tier)
  - [green]GitHub Models[/green] (free with GitHub account)
  - [yellow]OpenAI[/yellow] (paid, best general quality)
  - [yellow]Anthropic Claude[/yellow] (paid, best for coding)
  - [yellow]DeepSeek[/yellow] (paid, very cheap)
  - [yellow]OpenRouter[/yellow] (paid, 100+ models via one API)

[bold]Smart router:[/bold]
  trio.ai automatically picks the cheapest available provider
  for each query (local → free → paid). Configure with:
  trio provider set --strategy free_first
""",
    "skill": """
[bold cyan]trio skill[/bold cyan] — Manage skills (3,876 in TrioHub).

[bold]Sub-commands:[/bold]
  trio skill list                       Show installed skills
  trio skill install <name>             Install from TrioHub
  trio skill install name1 name2 name3  Install multiple
  trio skill remove <name>              Remove an installed skill
  trio skill search "<query>"           Search local index

[bold]Browse the registry:[/bold]
  trio hub search "python"              Search all 3,876 skills
  trio hub trending                      Most popular skills
  trio hub trending --category coding   Filter by category

[bold]Categories:[/bold]
  General (415), Coding (418), SysAdmin (204), Productivity (167),
  Marketing (163), Web Dev (159), Data Science (102), Security (80),
  Creative (79), Finance (47), Legal (29), Education (25), Health (21)

[bold]Create your own:[/bold]
  Drop a markdown file in ~/.trio/skills/ with frontmatter:
  ---
  name: my_skill
  description: What this does
  tags: [coding, python]
  ---
  When the user asks X, do Y by ...
""",
    "daemon": """
[bold cyan]trio daemon[/bold cyan] — Run trio.ai as a background service.

[bold]Sub-commands:[/bold]
  trio daemon install     Install as systemd / launchd / Windows service
  trio daemon uninstall   Remove the service
  trio daemon start       Start the daemon
  trio daemon stop        Stop the daemon
  trio daemon restart     Restart the daemon
  trio daemon status      PID, uptime, channel health
  trio daemon logs        Tail recent logs

[bold]What it does:[/bold]
  - Runs all enabled chat channels in the background
  - Auto-restarts on crash
  - Survives reboots if you ran 'daemon install'
  - Health-monitored via the heartbeat system

[bold]Logs are at:[/bold]
  ~/.trio/logs/daemon.log
""",
    "train": """
[bold cyan]trio train[/bold cyan] — Train your own LLM from scratch.

[bold]Quick start:[/bold]
  trio train --setup           Download pre-trained GGUF models (recommended)
  trio train                    Train from scratch
  trio train --reset            Restart training (ignore checkpoints)

[bold]Model tiers:[/bold]
  - [green]trio-nano[/green]    ~1M params,  4 GB RAM,   CPU
  - [green]trio-small[/green]   ~125M params, 16 GB VRAM, T4 GPU (Kaggle/Colab)
  - [green]trio-medium[/green]  ~350M params, 24 GB VRAM, RTX 3090 / A100
  - [green]trio-high[/green]    ~750M params, 40 GB VRAM, A100
  - [green]trio-max[/green]     ~3B params,   80 GB VRAM, A100/H100
  - [green]trio-pro[/green]     ~30B MoE,     multi-GPU,  data center

[bold]Auto-detected:[/bold]
  trio.ai picks the right config for your hardware automatically.

[bold]Pause/resume:[/bold]
  Press Ctrl+C anytime — checkpoints are saved every 500 steps.
  Run 'trio train' again to resume from the last checkpoint.
""",
    "serve": """
[bold cyan]trio serve[/bold cyan] — Start the browser-based chat UI.

[bold]Usage:[/bold]
  trio serve                              Default: http://localhost:28337
  trio serve --port 8080                  Custom port
  trio serve --host 0.0.0.0               Listen on all interfaces

[bold]Authentication:[/bold]
  - API key auto-generated at ~/.trio/api_key
  - Local requests (127.0.0.1) bypass auth for convenience
  - Remote requests require: Authorization: Bearer <key>

[bold]Endpoints:[/bold]
  POST /api/chat              Send a message
  POST /api/chat/stream       Streaming chat (Server-Sent Events)
  POST /api/upload            Upload a file
  GET  /api/help              Get all commands as JSON
  GET  /api/skills            List skills
  GET  /api/providers         List configured providers

[bold]Web UI features:[/bold]
  - Markdown rendering with syntax highlighting
  - File upload (PDF, DOCX, code, images)
  - Skill browser with one-click install
  - Provider switcher
  - Session history
  - Memory viewer
""",
    "doctor": """
[bold cyan]trio doctor[/bold cyan] — Diagnose system issues.

[bold]Usage:[/bold]
  trio doctor              Check system health
  trio doctor --fix        Auto-repair common issues

[bold]What it checks:[/bold]
  ✓ Python version (3.10+)
  ✓ trio.ai package installation
  ✓ ~/.trio directory structure
  ✓ config.json validity
  ✓ Encrypted secrets accessibility
  ✓ Provider connectivity (Ollama, OpenAI, etc.)
  ✓ Channel credentials validity
  ✓ Plugin/skill manifest integrity
  ✓ Daemon status

[bold]Common fixes:[/bold]
  - Corrupted config → restored from backup
  - Missing skill files → re-downloaded
  - Broken Ollama connection → restart hint
  - Stale daemon PID → cleared
""",
}


def show_main_help() -> None:
    """Render the full command catalogue with categories."""
    console.print()
    console.print(Panel.fit(
        "[bold cyan]trio.ai[/bold cyan] — Train your own AI. Deploy it everywhere. Own it forever.\n"
        "[dim]https://github.com/iampopye/trio[/dim]",
        border_style="cyan",
    ))
    console.print()

    for category, commands in COMMAND_CATALOG.items():
        table = Table(
            title=f"[bold yellow]{category}[/bold yellow]",
            box=box.MINIMAL,
            show_header=False,
            title_justify="left",
            pad_edge=False,
        )
        table.add_column("Command", style="cyan", no_wrap=False)
        table.add_column("Description", style="white")
        for cmd, desc in commands:
            table.add_row(cmd, desc)
        console.print(table)
        console.print()

    console.print(
        "[dim]→ Use [cyan]trio help <command>[/cyan] for detailed help "
        "on a specific command.[/dim]"
    )
    console.print(
        "[dim]→ Full reference: "
        "[link]https://github.com/iampopye/trio/blob/main/COMMANDS.md[/link][/dim]"
    )
    console.print()


def show_command_help(command: str) -> None:
    """Show detailed help for a specific command."""
    cmd = command.lower().strip()
    if cmd in DETAILED_HELP:
        console.print(DETAILED_HELP[cmd])
    else:
        console.print(
            f"[yellow]No detailed help available for '{cmd}'.[/yellow]\n"
            f"Available: {', '.join(DETAILED_HELP.keys())}\n"
            f"Run [cyan]trio help[/cyan] to see all commands."
        )


async def run_help(command: str | None = None) -> None:
    """Entry point called from __main__.py."""
    if command:
        show_command_help(command)
    else:
        show_main_help()
