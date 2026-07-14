"""CommandContext — the single object every slash-command handler receives.

Carries EXACTLY the eight live refs `run_agent()` already builds, plus a rich
Console for formatted output and the fixed CLI session identity. Every ref is a
reference to the SAME live object the agent task uses, so mutating (e.g.)
`ctx.agent._user_models[ctx.session_key]` is immediately visible to the next
agent turn.
"""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from rich.console import Console

    from triobot.channels.cli_channel import CLIChannel
    from triobot.core.bus import MessageBus
    from triobot.core.loop import AgentLoop
    from triobot.core.memory import MemoryStore
    from triobot.core.session import SessionManager
    from triobot.providers.base import BaseProvider
    from triobot.tools.base import ToolRegistry
    from triobot.tools.mcp_client import MCPManager


@dataclass
class CommandContext:
    """The dependency bundle handed to every command handler.

    All eight refs may be None only in legacy/test construction of the channel;
    handlers should degrade gracefully (e.g. `/mcp` with mcp_manager=None prints
    "no MCP servers" rather than raising).
    """

    channel: "CLIChannel"  # screen clear, session-name label, publish_inbound
    config: dict[str, Any]  # live config dict (load_config() result)
    provider: "BaseProvider"  # running provider (list_models, supports_tools, ...)
    bus: "MessageBus"  # to publish inbound (e.g. @file-expanded prompts)
    sessions: "SessionManager"  # get/save/list/rename/delete
    memory: "MemoryStore"  # read_memory/read_history/search_history/save_memory_fact
    tools: "ToolRegistry"  # list_tools/get_schemas/execute
    mcp_manager: "MCPManager | None"  # None when no MCP servers configured
    agent: "AgentLoop"  # per-user modes/models/deepthink, session helpers
    console: "Console"  # rich console for formatted output

    # Canonical CLI identity (matches InboundMessage.session_key contract:
    # session_key = f"{channel}:{chat_id}"; the CLI publishes channel="cli",
    # chat_id="cli_user").
    channel_name: str = "cli"
    chat_id: str = "cli_user"

    @property
    def session_key(self) -> str:
        return f"{self.channel_name}:{self.chat_id}"
