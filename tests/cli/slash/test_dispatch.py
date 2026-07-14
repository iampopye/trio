"""Offline tests for the slash-command registry and dispatcher.

Proves the Phase 0 contract without a live provider or network:
    - the registry is non-empty and builds cleanly
    - /help dispatches and lists categories
    - unknown /foo returns not-handled (falls through to the LLM)
    - !echo hi runs the shell path and returns output without hitting the LLM
    - @file expands file content and routes to the LLM
    - @file blocks path traversal outside the workspace/cwd roots
    - a handler that raises is caught and never crashes the loop
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT.

from __future__ import annotations

import pytest

from triobot.cli.slash import build_registry, dispatch, render_help
from triobot.cli.slash.model import Category, CommandResult
from triobot.cli.slash.registry import CANONICAL, REGISTRY, command


# ── Registry ──────────────────────────────────────────────────────────────────


def test_registry_is_non_empty_after_build():
    """build_registry() imports the command modules and populates REGISTRY."""
    # Arrange / Act
    reg = build_registry()

    # Assert
    assert len(reg) > 0
    assert len(CANONICAL) > 0
    # The five migrated commands must all resolve.
    for name in ("help", "provider", "model", "skill", "clear"):
        assert name in reg


def test_registry_entries_are_well_formed():
    """Every canonical command has a summary and a usage starting with '/'."""
    build_registry()
    for cmd in CANONICAL:
        assert cmd.summary, f"{cmd.name} has an empty summary"
        assert cmd.usage.startswith("/"), f"{cmd.name} usage is malformed"
        assert isinstance(cmd.category, Category)
        assert cmd.phase in {"P1", "P2", "P3", "P4"}


def test_duplicate_command_raises_value_error():
    """Registering the same name twice raises at decoration time."""
    build_registry()

    with pytest.raises(ValueError):

        @command("help", category=Category.SYSTEM, summary="dup")
        async def _dup(ctx, arg):  # pragma: no cover - never called
            return CommandResult()


# ── Dispatch: /help ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_help_is_handled_and_lists_categories(ctx):
    """/help dispatches, is handled, and includes category headings."""
    # Arrange
    build_registry()

    # Act
    res = await dispatch("/help", ctx)

    # Assert
    assert res.handled is True
    assert "Session & Context" in res.message
    assert "Model & Provider" in res.message
    # And render_help agrees.
    assert "triobot slash commands" in render_help()


# ── Dispatch: unknown slash ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_slash_falls_through_to_llm(ctx):
    """An unregistered /foo returns handled=False so the channel sends to LLM."""
    # Arrange
    build_registry()

    # Act
    res = await dispatch("/foo", ctx)

    # Assert
    assert res.handled is False
    assert res.send_to_llm is None


# ── Dispatch: !shell ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_bang_runs_shell_without_llm(ctx):
    """!echo hi executes locally via the shell path and is handled."""
    # Act
    res = await dispatch("!echo hi", ctx)

    # Assert
    assert res.handled is True
    assert "hi" in res.message
    assert res.send_to_llm is None


@pytest.mark.asyncio
async def test_bang_empty_shows_usage(ctx):
    """A bare ! shows usage rather than crashing."""
    res = await dispatch("!", ctx)
    assert res.handled is True
    assert "Usage" in res.message


# ── Dispatch: @file ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_at_file_expands_and_routes_to_llm(tmp_path, monkeypatch, ctx):
    """@note.txt inlines the file content and routes it to the LLM."""
    # Arrange: create a file under a fake workspace root.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    (workspace / "note.txt").write_text("SECRET-CONTENT", encoding="utf-8")
    monkeypatch.setattr(
        "triobot.cli.slash.special.get_workspace_dir", lambda: workspace
    )

    # Act
    res = await dispatch("summarize @note.txt", ctx)

    # Assert
    assert res.handled is False
    assert res.send_to_llm is not None
    assert "SECRET-CONTENT" in res.send_to_llm


@pytest.mark.asyncio
async def test_at_file_blocks_path_traversal(tmp_path, monkeypatch, ctx):
    """@../../etc/passwd escapes every root → treated as normal input."""
    # Arrange: workspace and cwd both inside tmp_path so traversal is out-of-bounds.
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setattr(
        "triobot.cli.slash.special.get_workspace_dir", lambda: workspace
    )
    monkeypatch.chdir(workspace)

    # Act
    res = await dispatch("read @../../../../../../etc/passwd", ctx)

    # Assert: traversal rejected, nothing expanded, still normal chat input.
    assert res.handled is False
    assert res.send_to_llm is None


@pytest.mark.asyncio
async def test_plain_at_without_file_is_untouched(ctx):
    """A bare @ that resolves to no file is left as normal input."""
    res = await dispatch("email me @someone", ctx)
    assert res.handled is False
    assert res.send_to_llm is None


# ── Dispatch: handler exception is caught ─────────────────────────────────────


@pytest.mark.asyncio
async def test_handler_exception_does_not_crash(ctx):
    """A handler that raises yields a graceful error result, not an exception."""
    # Arrange: register a throwaway command that always explodes.
    if "boom" not in REGISTRY:

        @command("boom", category=Category.SYSTEM, summary="explodes for tests")
        async def _boom(ctx, arg):
            raise RuntimeError("kaboom")

    # Act: dispatch must swallow the exception.
    res = await dispatch("/boom", ctx)

    # Assert
    assert res.handled is True
    assert "failed" in res.message.lower()
    assert "kaboom" in res.message


# ── Dispatch: normal input ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_plain_text_is_not_handled(ctx):
    """Ordinary chat text is not handled locally."""
    res = await dispatch("what is the weather today", ctx)
    assert res.handled is False
    assert res.send_to_llm is None
