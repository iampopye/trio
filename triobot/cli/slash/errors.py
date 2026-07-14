"""Slash-command error types.

These are lightweight signals a handler may raise; dispatch() catches all
exceptions and converts them to a graceful CommandResult so a bad command
never crashes the REPL loop.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations


class SlashError(Exception):
    """Base class for slash-command errors."""


class UnknownCommand(SlashError):
    """Raised when a verb does not resolve to a registered command."""


class BadUsage(SlashError):
    """Raised when a command is invoked with invalid arguments."""
