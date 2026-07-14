"""Fakes and fixtures for offline slash-command tests.

No live provider, no network. SessionManager and MemoryStore accept an injected
directory so tests use tmp_path and never touch ~/.trio.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT.

from __future__ import annotations

from types import SimpleNamespace

import pytest


class FakeProvider:
    """Minimal provider — list_models() is the only method dispatch may call."""

    async def list_models(self):
        return ["llama3.2:3b", "llama3.1:8b"]

    def supports_tools(self):
        return False

    def supports_vision(self):
        return False


class FakeChannel:
    """Stand-in for CLIChannel (only what commands touch)."""

    def __init__(self):
        self.cleared = False
        self._session_name = None

    def set_session_name(self, name):
        self._session_name = name


class FakeAgent:
    """Stand-in for AgentLoop exposing the live per-user state dicts."""

    def __init__(self):
        self._user_modes: dict[str, str] = {}
        self._user_models: dict[str, str] = {}
        self._deep_thinking: dict[str, bool] = {}
        self.memory_window = 20
        self.default_model = "llama3.1:8b"
        self.subagent_registry = SimpleNamespace(list_agents=lambda: [])


def make_ctx(tmp_path, **over):
    """Build a CommandContext wired to fakes and tmp-backed stores."""
    from rich.console import Console

    from triobot.cli.slash import CommandContext
    from triobot.core.memory import MemoryStore
    from triobot.core.session import SessionManager
    from triobot.tools.base import ToolRegistry
    from triobot.tools.shell import ShellTool

    tools = ToolRegistry()
    tools.register(ShellTool())  # policy-guarded shell path for !shell tests

    base = dict(
        channel=FakeChannel(),
        config={"agents": {"defaults": {"provider": "ollama", "model": "llama3.1:8b"}}},
        provider=FakeProvider(),
        bus=None,
        sessions=SessionManager(data_dir=tmp_path / "s"),
        memory=MemoryStore(memory_dir=tmp_path / "m"),
        tools=tools,
        mcp_manager=None,
        agent=FakeAgent(),
        console=Console(),
    )
    base.update(over)
    return CommandContext(**base)


@pytest.fixture
def ctx(tmp_path):
    """A ready-to-use CommandContext for the current tmp_path."""
    return make_ctx(tmp_path)
