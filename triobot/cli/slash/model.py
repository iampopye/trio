"""Slash-command value objects: Category, CommandResult, SlashCommand.

These are frozen dataclasses — commands and their results are values, never
mutated in place (see coding-style immutability rule).
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from triobot.cli.slash.context import CommandContext


class Category(str, Enum):
    """Command groupings for the auto-generated /help table (stable order)."""

    SESSION = "Session & Context"
    MODEL = "Model & Provider"
    AGENTS = "Agents, Tools, MCP & Skills"
    DEV = "Dev Workflow"
    SYSTEM = "System & Config"
    NATIVE = "triobot-native"


@dataclass(frozen=True)
class CommandResult:
    """Immutable result of a command.

    Attributes:
        message: Text printed by the channel (rich markup allowed).
        handled: True stops the line from being sent to the LLM.
        exit_repl: True requests the REPL to quit.
        send_to_llm: Optional text to route to the LLM (e.g. an @file-expanded
            prompt). When set, the channel sends this instead of the raw line.
    """

    message: str = ""
    handled: bool = True
    exit_repl: bool = False
    send_to_llm: str | None = None


# Handler signature: async (ctx, arg) -> CommandResult
Handler = Callable[["CommandContext", str], Awaitable[CommandResult]]


@dataclass(frozen=True)
class SlashCommand:
    """A registered slash command. Frozen — commands are values."""

    name: str  # canonical, no leading slash, e.g. "model"
    handler: Handler
    category: Category
    summary: str  # one-line description for /help
    usage: str = ""  # e.g. "/model <name>"
    aliases: tuple[str, ...] = ()  # e.g. ("new", "reset")
    phase: str = "P1"  # P1 | P2 | P3 | P4 — informational / gating
