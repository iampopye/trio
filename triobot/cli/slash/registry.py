"""The @command decorator, the REGISTRY, and registry helpers.

Adding a command anywhere in `slash/commands/` is purely additive: decorate a
handler with @command(...) inside an already-imported category module. Duplicate
names or aliases raise at import time — fail fast to catch merge collisions.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

from triobot.cli.slash.model import Category, Handler, SlashCommand

# name/alias -> SlashCommand  (aliases point at the SAME object)
REGISTRY: dict[str, SlashCommand] = {}
# ordered canonical list for /help (one entry per command, not per alias)
CANONICAL: list[SlashCommand] = []


def command(
    name: str,
    *,
    category: Category,
    summary: str,
    usage: str = "",
    aliases: tuple[str, ...] | list[str] = (),
    phase: str = "P1",
):
    """Register a handler as a SlashCommand.

    Raises ValueError at decoration (import) time on a duplicate name or alias.
    """

    def wrap(fn: Handler) -> Handler:
        cmd = SlashCommand(
            name=name,
            handler=fn,
            category=category,
            summary=summary,
            usage=usage or f"/{name}",
            aliases=tuple(aliases),
            phase=phase,
        )
        for key in (name, *cmd.aliases):
            if key in REGISTRY:
                raise ValueError(f"Duplicate slash command/alias: /{key}")
            REGISTRY[key] = cmd
        CANONICAL.append(cmd)
        return fn

    return wrap


def build_registry() -> dict[str, SlashCommand]:
    """Import every command module so decorators run, then return REGISTRY.

    Import is idempotent; safe to call once per REPL start.
    """
    from triobot.cli.slash import commands  # noqa: F401  (imports every category module)

    return REGISTRY


def resolve(verb: str) -> SlashCommand | None:
    """Look up a command by canonical name or alias (case-insensitive)."""
    return REGISTRY.get(verb.lower())
