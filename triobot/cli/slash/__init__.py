"""triobot interactive slash-command system.

Public surface:
    dispatch(line, ctx) -> CommandResult   single entry point for the channel
    command(...)                            decorator to register a command
    build_registry() -> dict                import commands, return REGISTRY
    render_help(category=None) -> str       auto-generated grouped help
    CommandContext                          the 8-ref dependency bundle
    CommandResult, SlashCommand, Category   value objects
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

from triobot.cli.slash.context import CommandContext
from triobot.cli.slash.dispatch import dispatch
from triobot.cli.slash.help import render_help
from triobot.cli.slash.model import Category, CommandResult, SlashCommand
from triobot.cli.slash.registry import build_registry, command, resolve

__all__ = [
    "dispatch",
    "command",
    "build_registry",
    "resolve",
    "render_help",
    "CommandContext",
    "CommandResult",
    "SlashCommand",
    "Category",
]
