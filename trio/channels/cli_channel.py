"""CLI channel — interactive terminal chat for `trio agent`."""

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
        self._current_response = ""
        self._streaming = False

    async def start(self) -> None:
        """Start reading user input from terminal."""
        logger.info("CLI channel started")

    async def stop(self) -> None:
        self._running = False

    async def send_message(self, chat_id: str, content: str) -> None:
        """Print final message to terminal."""
        if self._streaming:
            # Clear the streaming line and print final
            print()  # New line after streaming
            self._streaming = False
            self._current_response = ""

        # Print the response
        print(f"\n{content}\n")

    async def send_stream_chunk(self, chat_id: str, chunk: StreamChunk) -> None:
        """Print streaming chunks in real-time."""
        if chunk.is_final:
            if self._streaming:
                print()  # New line
                self._streaming = False
                self._current_response = ""
            return

        if chunk.chunk:
            print(chunk.chunk, end="", flush=True)
            self._streaming = True

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

                # Publish to bus
                await self.publish_inbound(
                    chat_id="cli_user",
                    user_id="cli_user",
                    content=user_input.strip(),
                )

                # Wait a moment for processing to begin
                await asyncio.sleep(0.1)

                # Wait for response to complete
                await self._wait_for_response()

            except (KeyboardInterrupt, EOFError):
                print("\nGoodbye!")
                self._running = False
                break

    def _get_input(self) -> str | None:
        """Read a line from stdin (blocking, runs in thread)."""
        try:
            return input("You: ")
        except (KeyboardInterrupt, EOFError):
            return None

    async def _wait_for_response(self) -> None:
        """Wait until the agent finishes responding."""
        # Simple approach: wait for a final outbound message
        timeout = 180  # 3 minutes max
        start = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start < timeout:
            await asyncio.sleep(0.05)
            # Check if we got a final response (indicated by non-streaming state)
            if not self._streaming and self._current_response == "":
                # Give a bit more time for the response to arrive
                await asyncio.sleep(0.5)
                break
