"""CLI channel — interactive terminal chat for `trio agent`."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import sys
import logging

from triobot.channels.base import BaseChannel
from triobot.core.bus import MessageBus, StreamChunk, OutboundMessage

logger = logging.getLogger(__name__)


class CLIChannel(BaseChannel):
    """Interactive terminal channel for `trio agent` mode."""

    def __init__(
        self,
        bus: MessageBus,
        config: dict | None = None,
        *,
        provider=None,
        sessions=None,
        memory=None,
        tools=None,
        mcp_manager=None,
        agent=None,
        console=None,
    ):
        super().__init__(name="cli", bus=bus, config=config or {})
        self._running = True
        self._streaming = False
        self._streamed_content = False
        self._session_name: str | None = None
        self._response_done = asyncio.Event()
        # Slash-command dependencies (may be None in legacy/test construction).
        self._provider = provider
        self._sessions = sessions
        self._memory = memory
        self._tools = tools
        self._mcp_manager = mcp_manager
        self._agent = agent
        self._console = console
        self._ctx = None  # built lazily on first command
        self._registry_ready = False

    async def start(self) -> None:
        """Start reading user input from terminal."""
        logger.info("CLI channel started")

    async def stop(self) -> None:
        self._running = False
        self._response_done.set()  # Unblock any waiting

    async def send_message(self, chat_id: str, content: str) -> None:
        """Print final message to terminal."""
        if self._streaming:
            print()  # New line after streaming
            self._streaming = False

        if self._streamed_content:
            # Content was already shown via streaming — only print stats line
            stats_start = content.rfind("\n\n_(")
            if stats_start >= 0:
                print(content[stats_start:])
            self._streamed_content = False
        else:
            print(f"\ntrio: {content}\n")

        # Signal that response is complete
        self._response_done.set()

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Print streaming chunks in real-time."""
        if chunk.is_final:
            if self._streaming:
                print()  # New line
                self._streaming = False
            return

        if chunk.chunk:
            if not self._streaming:
                print("\ntrio: ", end="", flush=True)
            print(chunk.chunk, end="", flush=True)
            self._streaming = True
            self._streamed_content = True

    async def run_interactive(self) -> None:
        """Run the interactive input loop."""
        exit_commands = {"exit", "quit", "/exit", "/quit", ":q"}

        print("\ntrio - the open agent framework for every platform")
        print("Type 'exit' to quit, '/help' for slash commands\n")

        while self._running:
            try:
                # Read input
                user_input = await asyncio.to_thread(self._get_input)

                if user_input is None or user_input.strip().lower() in exit_commands:
                    print("\nGoodbye!")
                    self._running = False
                    break

                stripped = user_input.strip()
                if not stripped:
                    continue

                # Slash commands, !shell escapes, and @file lines all route
                # through the registry dispatcher first (local, no LLM).
                if (
                    stripped.startswith("/")
                    or stripped.startswith("!")
                    or "@" in stripped
                ):
                    handled = await self._handle_slash_command(stripped)
                    if handled:
                        if not self._running:
                            break
                        continue

                # Normal chat input → send to the LLM.
                await self._route_to_llm(stripped)

            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                self._running = False
                break

    def _get_context(self):
        """Build the CommandContext once, on demand, from the stored refs."""
        if self._ctx is None:
            from triobot.cli.slash import CommandContext
            from triobot.cli.slash.registry import build_registry

            if not self._registry_ready:
                build_registry()
                self._registry_ready = True

            if self._console is None:
                from rich.console import Console

                self._console = Console()

            self._ctx = CommandContext(
                channel=self,
                config=self.config,
                provider=self._provider,
                bus=self.bus,
                sessions=self._sessions,
                memory=self._memory,
                tools=self._tools,
                mcp_manager=self._mcp_manager,
                agent=self._agent,
                console=self._console,
            )
        return self._ctx

    async def _handle_slash_command(self, cmd: str) -> bool:
        """Route a slash / ! / @ line through the registry.

        Returns True if handled locally (no LLM round-trip needed).
        """
        from triobot.cli.slash import dispatch

        result = await dispatch(cmd, self._get_context())

        if result.message:
            self._console.print(result.message)

        if result.exit_repl:
            print("\nGoodbye!")
            self._running = False
            return True

        if result.send_to_llm is not None:
            # @file expansion etc. — route the rewritten text to the LLM.
            await self._route_to_llm(result.send_to_llm)
            return True

        return result.handled

    async def _route_to_llm(self, text: str) -> None:
        """Publish `text` to the bus and wait for the response to complete."""
        self._response_done.clear()
        await self.publish_inbound(
            chat_id="cli_user",
            user_id="cli_user",
            content=text,
        )
        try:
            await asyncio.wait_for(self._response_done.wait(), timeout=300)
        except asyncio.TimeoutError:
            print("\n[timeout — no response after 5 minutes]\n")
        print()  # Blank line before next prompt

    def set_session_name(self, name: str | None):
        """Set the current session name for the prompt."""
        self._session_name = name

    def _get_input(self) -> str | None:
        """Read a line from stdin (blocking, runs in thread)."""
        try:
            prompt = f"[{self._session_name}] You: " if self._session_name else "You: "
            return input(prompt)
        except (KeyboardInterrupt, EOFError):
            return None
