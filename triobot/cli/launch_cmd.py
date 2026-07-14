"""``triobot`` — honest launcher for the provider-agnostic agent framework.

triobot is a provider-agnostic AI agent framework: you bring your own model
(Ollama or any OpenAI-compatible / API provider) and triobot runs the agent,
tools, memory, and 17 chat channels on top of it.

This module backs two entry points (see ``pyproject.toml``):

- the standalone ``triobot`` console command → :func:`main`
- the ``trio launch`` subcommand → :func:`run_launch`

Both do the same small, honest thing: if a provider is configured, hand off to
the chat runtime; otherwise guide the user to run ``trio onboard`` to pick a
provider. No model downloads, no bundled model lineup.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

import argparse
import asyncio
import sys

from rich.console import Console

from triobot import __version__
from triobot.core.config import get_config_path, load_config

console = Console()

# Exit codes — narrow, documented, scriptable.
EXIT_OK = 0
EXIT_NOT_CONFIGURED = 1
EXIT_CANCELLED = 130


# ── Public entry points ───────────────────────────────────────────────────────

def main() -> None:
    """Synchronous entry point used by the ``triobot`` console script."""
    parser = _build_arg_parser()
    args = parser.parse_args()

    try:
        exit_code = asyncio.run(run_launch(no_launch=args.no_launch))
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled.[/yellow]")
        sys.exit(EXIT_CANCELLED)
    sys.exit(exit_code)


async def run_launch(*, no_launch: bool = False) -> int:
    """Ensure a provider is configured, then drop into chat.

    Returns a process exit code. If no config exists yet, prints onboarding
    guidance and returns without launching.
    """
    if not get_config_path().exists():
        _print_onboarding_help()
        return EXIT_NOT_CONFIGURED

    config = load_config()
    defaults = config.get("agents", {}).get("defaults", {})
    provider = defaults.get("provider", "ollama")
    model = defaults.get("model") or "(not set)"

    console.print(
        f"[bold cyan]triobot[/bold cyan] [dim]v{__version__}[/dim] — "
        f"provider [cyan]{provider}[/cyan], model [cyan]{model}[/cyan]"
    )

    if no_launch:
        console.print(
            "[green]Ready.[/green] Start a chat anytime with [cyan]trio agent[/cyan]."
        )
        return EXIT_OK

    # Hand off to the shared chat runtime. Local import keeps startup snappy.
    from triobot.cli.agent import run_agent
    await run_agent(message=None, no_markdown=False, show_logs=False)
    return EXIT_OK


# ── CLI ───────────────────────────────────────────────────────────────────────

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="triobot",
        description=(
            "Launch the triobot agent. Bring your own model via Ollama or any "
            "OpenAI-compatible / API provider (configure with 'trio onboard')."
        ),
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Report the configured provider/model but don't open chat.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"triobot {__version__}",
    )
    return parser


def _print_onboarding_help() -> None:
    console.print(
        "[yellow]No configuration found.[/yellow]\n"
        "triobot is provider-agnostic — you bring your own model.\n\n"
        "Run [cyan]trio onboard[/cyan] to pick a provider (Ollama for a local "
        "model, or an OpenAI-compatible / API provider) and set up your "
        "workspace, then start chatting with [cyan]trio agent[/cyan]."
    )


__all__ = ["main", "run_launch"]
