"""CLI channel — interactive terminal chat for `trio agent`."""

# Copyright (c) 2026 Karan Garg. Licensed under MIT. See LICENSE file.

import asyncio
import sys
import logging

from trio.channels.base import BaseChannel
from trio.core.bus import MessageBus, StreamChunk, OutboundMessage

logger = logging.getLogger(__name__)


class CLIChannel(BaseChannel):
    """Interactive terminal channel for `trio agent` mode."""

    def __init__(self, bus: MessageBus, config: dict | None = None):
        super().__init__(name="cli", bus=bus, config=config or {})
        self._running = True
        self._streaming = False
        self._streamed_content = False
        self._session_name: str | None = None
        self._response_done = asyncio.Event()

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
        print("Type 'exit' to quit, '/help' for commands\n")

        while self._running:
            try:
                # Read input
                user_input = await asyncio.to_thread(self._get_input)

                if user_input is None or user_input.strip().lower() in exit_commands:
                    print("\nGoodbye!")
                    self._running = False
                    break

                if not user_input.strip():
                    continue

                # Reset response event
                self._response_done.clear()

                # Publish to bus
                await self.publish_inbound(
                    chat_id="cli_user",
                    user_id="cli_user",
                    content=user_input.strip(),
                )

                # Wait for response to complete
                try:
                    await asyncio.wait_for(self._response_done.wait(), timeout=300)
                except asyncio.TimeoutError:
                    print("\n[timeout — no response after 5 minutes]\n")

                print()  # Blank line before next prompt

            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                self._running = False
                break

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
